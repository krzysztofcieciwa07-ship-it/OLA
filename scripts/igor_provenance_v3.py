"""Independent OLA v3 evidence-chain and signed-checkpoint verifier.

This module intentionally does not import agent runtime, supervisor, or ledger writer code.
"""

import base64
import hashlib
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


GENESIS_HASH = "0" * 64
CHECKPOINT_DOMAIN = "OLA-LEDGER-CHECKPOINT-V1"


def canonical_bytes(value: Any) -> bytes:
    return rfc8785.dumps(value)


def record_hash(record: dict) -> str:
    payload = {
        "tenant_id": record["tenant_id"],
        "seq": record["seq"],
        "prev_hash": record["prev_hash"],
        "record_type": record["record_type"],
        "producer_id": record["producer_id"],
        "payload": record["payload"],
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def verify_event_chain(records: list[dict]) -> dict:
    if not isinstance(records, list) or not records:
        return {"status": "BLOCKED", "reason": "ledger_empty"}
    if not isinstance(records[0], dict):
        return {"status": "BLOCKED", "reason": "ledger_record_invalid"}
    tenant_id = records[0].get("tenant_id")
    previous = GENESIS_HASH
    for expected_seq, record in enumerate(records):
        if not isinstance(record, dict):
            return {"status": "BLOCKED", "reason": "ledger_record_invalid"}
        if record.get("tenant_id") != tenant_id:
            return {"status": "BLOCKED", "reason": "ledger_tenant_mismatch"}
        if type(record.get("seq")) is not int or record["seq"] != expected_seq:
            return {"status": "BLOCKED", "reason": "ledger_sequence_gap"}
        if record.get("prev_hash") != previous:
            return {"status": "BLOCKED", "reason": "ledger_previous_hash_mismatch"}
        try:
            expected_hash = record_hash(record)
        except (KeyError, TypeError, ValueError):
            return {"status": "BLOCKED", "reason": "ledger_record_invalid"}
        if record.get("record_hash") != expected_hash:
            return {"status": "BLOCKED", "reason": "ledger_record_hash_mismatch"}
        previous = expected_hash
    return {
        "status": "VERIFIED",
        "reason": None,
        "tenant_id": tenant_id,
        "seq": len(records) - 1,
        "head_hash": previous,
    }


def checkpoint_payload(checkpoint: dict) -> dict:
    return {
        "domain": CHECKPOINT_DOMAIN,
        "schema_version": checkpoint["schema_version"],
        "tenant_id": checkpoint["tenant_id"],
        "seq": checkpoint["seq"],
        "head_hash": checkpoint["head_hash"],
        "previous_checkpoint_hash": checkpoint["previous_checkpoint_hash"],
        "issued_at": checkpoint["issued_at"],
        "signer_key_id": checkpoint["signer_key_id"],
    }


def verify_signed_checkpoint(records: list[dict], checkpoint: dict,
                              trusted_public_key: str | bytes) -> dict:
    chain = verify_event_chain(records)
    if chain["status"] != "VERIFIED":
        return chain
    try:
        if checkpoint.get("schema_version") != 1 or checkpoint.get("domain") != CHECKPOINT_DOMAIN:
            return {"status": "BLOCKED", "reason": "checkpoint_schema_unsupported"}
        if checkpoint.get("tenant_id") != chain["tenant_id"]:
            return {"status": "BLOCKED", "reason": "checkpoint_tenant_mismatch"}
        if checkpoint.get("seq") != chain["seq"]:
            return {"status": "BLOCKED", "reason": "checkpoint_sequence_mismatch"}
        if checkpoint.get("head_hash") != chain["head_hash"]:
            return {"status": "BLOCKED", "reason": "checkpoint_head_mismatch"}
        if isinstance(trusted_public_key, str):
            public_bytes = base64.b64decode(trusted_public_key, validate=True)
        else:
            public_bytes = trusted_public_key
        signature = base64.b64decode(checkpoint["signature"], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(signature, canonical_bytes(checkpoint_payload(checkpoint)))
    except (KeyError, TypeError, ValueError, InvalidSignature):
        return {"status": "BLOCKED", "reason": "checkpoint_signature_invalid"}
    return {
        "status": "VERIFIED",
        "reason": None,
        "tenant_id": chain["tenant_id"],
        "seq": chain["seq"],
        "head_hash": chain["head_hash"],
        "signer_key_id": checkpoint["signer_key_id"],
    }
