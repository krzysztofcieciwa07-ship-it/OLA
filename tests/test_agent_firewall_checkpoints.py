import base64
import copy
import hashlib
import json
import os
import threading
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.agent_firewall_signer import CheckpointSigner, CheckpointUnixServer, SignerError
from scripts.igor_agent_firewall import (
    GENESIS_HASH,
    canonical_json,
    verify_checkpoint_chain,
    verify_firewall_evidence,
    verify_signed_checkpoint,
)
from app.agent_firewall.checkpoints import UnixCheckpointSignerClient


def _records(count=2, tenant_id="tenant-firewall-test"):
    records = []
    previous = GENESIS_HASH
    for seq in range(count):
        record_type = "firewall.request.received"
        payload = {
            "request_id": str(uuid.UUID(int=seq + 1)),
            "__ola_evidence_v2__": {
                "version": 2,
                "record_type": record_type,
                "producer": "ola_runtime",
            },
        }
        payload_json = canonical_json(payload)
        material = canonical_json({
            "domain": "OLA-EVIDENCE-CHAIN-V2",
            "tenant_id": tenant_id,
            "seq": seq,
            "prev_hash": previous,
            "record_type": record_type,
            "producer": "ola_runtime",
            "payload_json": payload_json,
        }).encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()
        records.append({
            "tenant_id": tenant_id,
            "seq": seq,
            "prev_hash": previous,
            "record_hash": digest,
            "record_type": record_type,
            "payload_json": payload_json,
        })
        previous = digest
    return records


def _rehash(records):
    previous = GENESIS_HASH
    for seq, record in enumerate(records):
        record["seq"] = seq
        record["prev_hash"] = previous
        payload = json.loads(record["payload_json"])
        producer = payload["__ola_evidence_v2__"]["producer"]
        material = canonical_json({
            "domain": "OLA-EVIDENCE-CHAIN-V2",
            "tenant_id": record["tenant_id"],
            "seq": seq,
            "prev_hash": previous,
            "record_type": record["record_type"],
            "producer": producer,
            "payload_json": record["payload_json"],
        }).encode("utf-8")
        record["record_hash"] = hashlib.sha256(material).hexdigest()
        previous = record["record_hash"]
    return records


def _private_key_file(path):
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
    return base64.b64encode(public).decode("ascii"), hashlib.sha256(public).hexdigest()


def test_separate_signer_and_igor_verify_signed_checkpoint(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _public_b64, public_sha = _private_key_file(key_path)
    records = _records()
    signer = CheckpointSigner(key_path, state_path, signer_key_id="test-signer")

    checkpoint = signer.sign("tenant-firewall-test", records)
    result = verify_firewall_evidence(
        records, checkpoint, trusted_signer_sha256=public_sha
    )

    assert result["status"] == "VERIFIED"
    assert result["scope"] == "ledger_integrity_and_checkpoint_signature"
    assert result["not_established"]


def test_tamper_then_rehash_is_blocked_by_external_checkpoint(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _public_b64, public_sha = _private_key_file(key_path)
    original = _records()
    signer = CheckpointSigner(key_path, state_path, signer_key_id="test-signer")
    checkpoint = signer.sign("tenant-firewall-test", original)

    mutated = copy.deepcopy(original)
    payload = json.loads(mutated[0]["payload_json"])
    payload["request_id"] = "forged-request"
    mutated[0]["payload_json"] = canonical_json(payload)
    _rehash(mutated)

    result = verify_firewall_evidence(
        mutated, checkpoint, trusted_signer_sha256=public_sha
    )
    assert result == {"status": "BLOCKED", "reason": "checkpoint_head_mismatch"}
    with pytest.raises(SignerError, match="checkpoint_history_rewritten"):
        signer.sign("tenant-firewall-test", mutated)


def test_signer_requires_monotonic_checkpoint_advance(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _private_key_file(key_path)
    signer = CheckpointSigner(key_path, state_path, signer_key_id="test-signer")
    records = _records()

    signer.sign("tenant-firewall-test", records)
    with pytest.raises(SignerError, match="checkpoint_not_advanced"):
        signer.sign("tenant-firewall-test", records)


def test_checkpoint_history_links_each_signed_checkpoint(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _public_b64, public_sha = _private_key_file(key_path)
    signer = CheckpointSigner(key_path, state_path, signer_key_id="test-signer")
    records = _records()
    first = signer.sign("tenant-firewall-test", records)
    second_records = _records(3)
    second = signer.sign("tenant-firewall-test", second_records)

    result = verify_checkpoint_chain([first, second], trusted_signer_sha256=public_sha)
    assert result["status"] == "VERIFIED"
    assert second["manifest"]["previous_checkpoint_sha256"] == hashlib.sha256(
        canonical_json(first).encode("utf-8")
    ).hexdigest()


def test_signer_private_key_requires_owner_only_permissions(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _private_key_file(key_path)
    key_path.chmod(0o644)
    with pytest.raises(PermissionError, match="mode 0600"):
        CheckpointSigner(key_path, state_path, signer_key_id="test-signer")


def test_signer_socket_client_verifies_pinned_public_key(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _public_b64, public_sha = _private_key_file(key_path)
    signer = CheckpointSigner(key_path, state_path, signer_key_id="test-signer")
    socket_path = tmp_path / "signer.sock"
    server = CheckpointUnixServer(socket_path, signer)
    os.chmod(socket_path, 0o660)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = UnixCheckpointSignerClient(str(socket_path), public_sha)
        result = client.sign("tenant-firewall-test", _records())
        assert verify_signed_checkpoint(
            result["checkpoint"], trusted_signer_sha256=public_sha
        )["status"] == "VERIFIED"
        assert result["history"][-1] == result["checkpoint"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_wrong_pinned_public_key_blocks_checkpoint(tmp_path):
    key_path = tmp_path / "signer.pem"
    state_path = tmp_path / "state" / "checkpoints.json"
    _public_b64, public_sha = _private_key_file(key_path)
    signer = CheckpointSigner(key_path, state_path, signer_key_id="test-signer")
    checkpoint = signer.sign("tenant-firewall-test", _records())

    result = verify_signed_checkpoint(
        checkpoint, trusted_signer_sha256="f" * 64
    )
    assert result["status"] == "BLOCKED"


def test_firewall_ledger_requires_trusted_v2_producer():
    from scripts.igor_agent_firewall import verify_evidence_chain
    record = {
        "tenant_id": "tenant-a",
        "seq": 0,
        "prev_hash": GENESIS_HASH,
        "record_hash": "0" * 64,
        "record_type": "firewall.request.received",
        "payload_json": canonical_json({
            "value": "forged",
            "__ola_evidence_v2__": {
                "version": 2,
                "record_type": "firewall.request.received",
                "producer": "tenant_api",
            },
        }),
    }
    assert verify_evidence_chain([record]) == {
        "status": "BLOCKED",
        "reason": "ledger_record_invalid",
    }
