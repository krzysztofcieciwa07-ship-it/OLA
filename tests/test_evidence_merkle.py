from copy import deepcopy
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evidence_merkle import (
    EvidenceCheckpointError,
    build_inclusion_proof,
    create_checkpoint,
    create_tenant_checkpoint,
    verify_checkpoint_signature,
    verify_inclusion_proof,
)
from app.hashchain import (
    GENESIS_HASH,
    TRUSTED_PRODUCER,
    compute_record_hash_v2,
    sealed_payload_json,
)


def make_chain(count=5, tenant_id="tenant-merkle-test"):
    records = []
    previous = GENESIS_HASH
    for seq in range(count):
        record_type = "workflow.checkpoint.test"
        payload_json = sealed_payload_json(record_type, {"index": seq})
        digest = compute_record_hash_v2(
            tenant_id, seq, previous, record_type, TRUSTED_PRODUCER, payload_json
        )
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


def make_key():
    return Ed25519PrivateKey.generate()


def checkpoint_for(records, key=None):
    return create_checkpoint(
        records,
        signing_key=key or make_key(),
        signer_key_id="test-evidence-checkpoint-key",
        created_at="2026-11-09T00:00:00Z",
    )


def test_checkpoint_verifies_chain_and_separates_signature_from_trust():
    records = make_chain(3)
    key = make_key()
    checkpoint = checkpoint_for(records, key)

    status = verify_checkpoint_signature(checkpoint)
    assert status["signature_valid"] is True
    assert status["signer_trusted"] is False
    assert status["signer_key_id"] == "test-evidence-checkpoint-key"

    public_raw = key.public_key().public_bytes_raw()
    import hashlib
    pinned = hashlib.sha256(public_raw).hexdigest()
    trusted_status = verify_checkpoint_signature(
        checkpoint, trusted_signer_sha256=pinned
    )
    assert trusted_status["signature_valid"] is True
    assert trusted_status["signer_trusted"] is True


@pytest.mark.parametrize("count", [1, 2, 3, 5, 6])
def test_inclusion_proofs_verify_for_odd_and_even_tree_sizes(count):
    records = make_chain(count)
    checkpoint = checkpoint_for(records)
    for index in range(count):
        proof = build_inclusion_proof(records, index, checkpoint)
        assert verify_inclusion_proof(checkpoint, proof) is True


def test_proof_requires_a_pinned_signer_when_policy_requests_it():
    records = make_chain(2)
    checkpoint = checkpoint_for(records)
    proof = build_inclusion_proof(records, 1, checkpoint)
    assert verify_inclusion_proof(
        checkpoint, proof, require_trusted_signer=True
    ) is False


def test_modified_payload_is_rejected_before_merkle_root_creation():
    records = make_chain(2)
    records[0]["payload_json"] = '{"index":999}'
    with pytest.raises(EvidenceCheckpointError, match="chain failed verification"):
        checkpoint_for(records)


def test_reordered_or_cross_tenant_records_are_rejected():
    records = make_chain(3)
    with pytest.raises(EvidenceCheckpointError, match="complete tenant chain"):
        checkpoint_for([records[1], records[0], records[2]])

    mixed = make_chain(2)
    mixed[1]["tenant_id"] = "another-tenant"
    with pytest.raises(EvidenceCheckpointError, match="only one tenant"):
        checkpoint_for(mixed)


def test_proof_tampering_missing_sibling_and_cross_tenant_replay_fail_closed():
    records = make_chain(5)
    checkpoint = checkpoint_for(records)
    proof = build_inclusion_proof(records, 4, checkpoint)

    changed_hash = deepcopy(proof)
    changed_hash["record_hash"] = "f" * 64
    assert verify_inclusion_proof(checkpoint, changed_hash) is False

    missing_sibling = deepcopy(proof)
    missing_sibling["siblings"].pop()
    assert verify_inclusion_proof(checkpoint, missing_sibling) is False

    cross_tenant = deepcopy(proof)
    cross_tenant["tenant_id"] = "another-tenant"
    assert verify_inclusion_proof(checkpoint, cross_tenant) is False

    wrong_index = deepcopy(proof)
    wrong_index["leaf_index"] = 0
    assert verify_inclusion_proof(checkpoint, wrong_index) is False


def test_checkpoint_manifest_tampering_invalidates_signature_and_proof():
    records = make_chain(2)
    checkpoint = checkpoint_for(records)
    proof = build_inclusion_proof(records, 0, checkpoint)
    altered = deepcopy(checkpoint)
    altered["manifest"]["merkle_root"] = "f" * 64
    assert verify_checkpoint_signature(altered)["signature_valid"] is False
    assert verify_inclusion_proof(altered, proof) is False


def test_single_leaf_checkpoint_has_empty_membership_path():
    records = make_chain(1)
    checkpoint = checkpoint_for(records)
    proof = build_inclusion_proof(records, 0, checkpoint)
    assert proof["siblings"] == []
    assert verify_inclusion_proof(checkpoint, proof) is True


def test_tenant_database_helper_reads_only_the_requested_tenant():
    from app.database import SessionLocal
    from app.main import append_record
    from app.models import Tenant

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add_all([
            Tenant(id=tenant_a, name="merkle-tenant-a"),
            Tenant(id=tenant_b, name="merkle-tenant-b"),
        ])
        db.commit()

    append_record(tenant_a, "customer.event", {"value": "tenant-a"})
    append_record(tenant_a, "customer.event", {"value": "tenant-a-2"})
    append_record(tenant_b, "customer.event", {"value": "tenant-b"})

    key = make_key()
    checkpoint = create_tenant_checkpoint(
        tenant_a,
        signing_key=key,
        signer_key_id="integration-test-key",
    )
    assert checkpoint["manifest"]["tenant_id"] == tenant_a
    assert checkpoint["manifest"]["record_count"] == 2
    assert verify_checkpoint_signature(checkpoint)["signature_valid"] is True


def test_empty_tenant_chain_cannot_be_checkpointed():
    with pytest.raises(EvidenceCheckpointError, match="empty evidence chain"):
        create_checkpoint(
            [],
            signing_key=make_key(),
            signer_key_id="test-empty-chain",
        )


def _resign_with_test_key(checkpoint, key):
    import base64
    import hashlib
    from app.hashchain import canonical_json

    signed_bytes = canonical_json(checkpoint["manifest"]).encode("utf-8")
    checkpoint["manifest_sha256"] = hashlib.sha256(signed_bytes).hexdigest()
    checkpoint["signature"]["value_b64"] = base64.b64encode(
        key.sign(signed_bytes)
    ).decode("ascii")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("chain_start_seq", False), ("chain_end_seq", True)],
)
def test_signed_manifest_sequence_fields_must_be_exact_integers(field, invalid_value):
    records = make_chain(2)
    key = make_key()
    checkpoint = checkpoint_for(records, key)
    checkpoint["manifest"][field] = invalid_value
    _resign_with_test_key(checkpoint, key)

    assert verify_checkpoint_signature(checkpoint)["signature_valid"] is False
