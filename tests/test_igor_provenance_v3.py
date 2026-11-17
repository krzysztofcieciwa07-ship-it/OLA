import base64
import copy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.checkpoint_signer import CheckpointSigner
from scripts.igor_provenance_v3 import (
    GENESIS_HASH,
    record_hash,
    verify_signed_checkpoint,
)


def _records(count=2):
    records = []
    previous = GENESIS_HASH
    for seq in range(count):
        record = {
            "tenant_id": "tenant-test",
            "seq": seq,
            "prev_hash": previous,
            "record_type": "test.event",
            "producer_id": "test-fixture",
            "payload": {"ordinal": seq, "status": "ok"},
        }
        record["record_hash"] = record_hash(record)
        records.append(record)
        previous = record["record_hash"]
    return records


def _rehash(records):
    previous = GENESIS_HASH
    for seq, record in enumerate(records):
        record["seq"] = seq
        record["prev_hash"] = previous
        record["record_hash"] = record_hash(record)
        previous = record["record_hash"]
    return records


def _write_private_key(path):
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    path.chmod(0o600)
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public).decode("ascii")


def test_checkpoint_signer_and_independent_igor_verify_a_valid_segment(tmp_path):
    key_path = tmp_path / "checkpoint-ed25519.pem"
    state_path = tmp_path / "signer-state.json"
    public_key = _write_private_key(key_path)
    records = _records()
    signer = CheckpointSigner(key_path, state_path)

    checkpoint = signer.sign(records, tenant_id="tenant-test")
    result = verify_signed_checkpoint(records, checkpoint, public_key)

    assert result["status"] == "VERIFIED"
    assert result["head_hash"] == records[-1]["record_hash"]
    assert result["seq"] == 1


def test_tamper_then_rehash_is_blocked_by_external_checkpoint(tmp_path):
    key_path = tmp_path / "checkpoint-ed25519.pem"
    state_path = tmp_path / "signer-state.json"
    public_key = _write_private_key(key_path)
    original = _records()
    signer = CheckpointSigner(key_path, state_path)
    checkpoint = signer.sign(original, tenant_id="tenant-test")

    mutated = copy.deepcopy(original)
    mutated[0]["payload"]["status"] = "forged"
    _rehash(mutated)

    verification = verify_signed_checkpoint(mutated, checkpoint, public_key)
    assert verification == {
        "status": "BLOCKED",
        "reason": "checkpoint_head_mismatch",
    }
    with pytest.raises(ValueError, match="checkpoint_history_rewritten"):
        signer.sign(mutated, tenant_id="tenant-test")


def test_checkpoint_signer_rejects_unprotected_private_key_file(tmp_path):
    key_path = tmp_path / "checkpoint-ed25519.pem"
    state_path = tmp_path / "signer-state.json"
    _write_private_key(key_path)
    key_path.chmod(0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        CheckpointSigner(key_path, state_path)


def test_independent_igor_rejects_sequence_gaps():
    records = _records()
    records[1]["seq"] = 3
    result = verify_signed_checkpoint(records, {
        "schema_version": 1,
        "domain": "OLA-LEDGER-CHECKPOINT-V1",
        "tenant_id": "tenant-test",
        "seq": 1,
        "head_hash": "0" * 64,
        "previous_checkpoint_hash": GENESIS_HASH,
        "issued_at": 1,
        "signer_key_id": "test",
        "signature": base64.b64encode(b"x" * 64).decode("ascii"),
    }, base64.b64encode(b"x" * 32).decode("ascii"))

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "ledger_sequence_gap"
