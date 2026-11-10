"""Independent OLA Agent Firewall evidence and checkpoint verifier.

This module deliberately does not import app runtime, database, or signer code.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


GENESIS_HASH = "0" * 64
EVIDENCE_META_KEY = "__ola_evidence_v2__"
TRUSTED_PRODUCER = "ola_runtime"
PUBLIC_PRODUCER = "tenant_api"
PRIVILEGED_PREFIXES = (
    "workflow.", "task.", "human.", "agent.", "provenance.", "decision.",
    "execution.", "verification.", "stripe.", "revenue.", "firewall.", "ledger.",
)
CHECKPOINT_SCHEMA = "ola.agent-firewall.ledger-checkpoint/v1"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON constant is not allowed")


def strict_json_loads(value: str):
    if not isinstance(value, str):
        raise ValueError("JSON must be text")
    return json.loads(
        value, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
    )


def _sha(value, field):
    if not isinstance(value, str) or not _HEX64_RE.fullmatch(value):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def _record_binding(record):
    payload = strict_json_loads(record["payload_json"])
    if not isinstance(payload, dict):
        raise ValueError("evidence payload must be an object")
    metadata = payload.get(EVIDENCE_META_KEY)
    if metadata is None:
        return payload, None
    if not isinstance(metadata, dict) or set(metadata) != {"version", "record_type", "producer"}:
        raise ValueError("evidence metadata is invalid")
    producer = metadata["producer"]
    record_type = record["record_type"]
    if (
        type(metadata["version"]) is not int or metadata["version"] != 2
        or metadata["record_type"] != record_type
        or producer not in (TRUSTED_PRODUCER, PUBLIC_PRODUCER)
        or (record_type.startswith(PRIVILEGED_PREFIXES) and producer != TRUSTED_PRODUCER)
    ):
        raise ValueError("evidence producer/type binding is invalid")
    if canonical_json(payload) != record["payload_json"]:
        raise ValueError("v2 evidence payload is not canonical JSON")
    return payload, producer


def _record_hash_v1(tenant_id, seq, prev_hash, payload_json):
    material = f"{tenant_id}|{seq}|{prev_hash}|{payload_json}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _record_hash_v2(tenant_id, seq, prev_hash, record_type, producer, payload_json):
    material = canonical_json({
        "domain": "OLA-EVIDENCE-CHAIN-V2",
        "tenant_id": tenant_id,
        "seq": seq,
        "prev_hash": prev_hash,
        "record_type": record_type,
        "producer": producer,
        "payload_json": payload_json,
    }).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def verify_evidence_chain(records: Sequence[Mapping], *, expected_tenant_id=None) -> dict:
    blocked = lambda reason: {"status": "BLOCKED", "reason": reason}
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence) or not records:
        return blocked("ledger_empty_or_invalid")
    previous = GENESIS_HASH
    tenant_id = expected_tenant_id
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            return blocked("ledger_record_invalid")
        try:
            current_tenant = record["tenant_id"]
            seq = record["seq"]
            prev_hash = record["prev_hash"]
            record_hash = _sha(record["record_hash"], "record_hash")
            record_type = record["record_type"]
            payload_json = record["payload_json"]
            if not isinstance(current_tenant, str) or not current_tenant.strip():
                return blocked("ledger_tenant_invalid")
            if tenant_id is None:
                tenant_id = current_tenant
            if current_tenant != tenant_id:
                return blocked("ledger_tenant_mismatch")
            if type(seq) is not int or seq != index:
                return blocked("ledger_sequence_gap")
            if _sha(prev_hash, "prev_hash") != previous:
                return blocked("ledger_previous_hash_mismatch")
            if not isinstance(record_type, str) or not record_type:
                return blocked("ledger_record_type_invalid")
            if not isinstance(payload_json, str):
                return blocked("ledger_payload_invalid")
            _payload, producer = _record_binding(record)
            if record_type.startswith(("firewall.", "ledger.")) and producer != TRUSTED_PRODUCER:
                return blocked("firewall_evidence_not_trusted")
            if producer is None:
                expected = _record_hash_v1(current_tenant, seq, prev_hash, payload_json)
            else:
                expected = _record_hash_v2(
                    current_tenant, seq, prev_hash, record_type, producer, payload_json
                )
            if not hmac.compare_digest(expected, record_hash):
                return blocked("ledger_record_hash_mismatch")
        except (KeyError, TypeError, ValueError, UnicodeError):
            return blocked("ledger_record_invalid")
        previous = record_hash
    return {
        "status": "VERIFIED",
        "tenant_id": tenant_id,
        "seq": len(records) - 1,
        "head_hash": previous,
        "record_count": len(records),
    }


def checkpoint_manifest_bytes(manifest: Mapping) -> bytes:
    return canonical_json(dict(manifest)).encode("utf-8")


def checkpoint_sha256(checkpoint: Mapping) -> str:
    return hashlib.sha256(canonical_json(dict(checkpoint)).encode("utf-8")).hexdigest()


def verify_signed_checkpoint(
    checkpoint: Mapping,
    *,
    trusted_signer_sha256: str,
) -> dict:
    blocked = {
        "status": "BLOCKED",
        "reason": "checkpoint_signature_invalid",
        "signer_trusted": False,
    }
    try:
        if not isinstance(checkpoint, Mapping) or set(checkpoint) != {"manifest", "manifest_sha256", "signature"}:
            return blocked
        manifest = checkpoint["manifest"]
        envelope = checkpoint["signature"]
        if not isinstance(manifest, Mapping) or set(manifest) != {
            "schema", "tenant_id", "seq", "head_hash",
            "previous_checkpoint_sha256", "issued_at", "signer_key_id",
        }:
            return blocked
        if not isinstance(envelope, Mapping) or set(envelope) != {
            "algorithm", "key_id", "public_key_raw_b64", "public_key_sha256", "value_b64",
        }:
            return blocked
        if manifest.get("schema") != CHECKPOINT_SCHEMA:
            return blocked
        tenant_id = manifest.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            return blocked
        seq = manifest.get("seq")
        if type(seq) is not int or seq < 0:
            return blocked
        head_hash = _sha(manifest.get("head_hash"), "head_hash")
        previous_hash = _sha(manifest.get("previous_checkpoint_sha256"), "previous_checkpoint_sha256")
        issued_at = manifest.get("issued_at")
        if type(issued_at) is not int or issued_at <= 0:
            return blocked
        key_id = manifest.get("signer_key_id")
        if not isinstance(key_id, str) or not key_id:
            return blocked
        if envelope.get("algorithm") != "Ed25519" or envelope.get("key_id") != key_id:
            return blocked
        public_raw = base64.b64decode(envelope["public_key_raw_b64"], validate=True)
        signature = base64.b64decode(envelope["value_b64"], validate=True)
        if len(public_raw) != 32 or len(signature) != 64:
            return blocked
        public_sha = hashlib.sha256(public_raw).hexdigest()
        if not hmac.compare_digest(public_sha, _sha(envelope.get("public_key_sha256"), "public_key_sha256")):
            return blocked
        if not hmac.compare_digest(public_sha, _sha(trusted_signer_sha256, "trusted_signer_sha256")):
            return blocked
        manifest_sha = hashlib.sha256(checkpoint_manifest_bytes(manifest)).hexdigest()
        if not hmac.compare_digest(manifest_sha, _sha(checkpoint.get("manifest_sha256"), "manifest_sha256")):
            return blocked
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature, checkpoint_manifest_bytes(manifest)
        )
        return {
            "status": "VERIFIED",
            "reason": None,
            "signer_trusted": True,
            "tenant_id": tenant_id,
            "seq": seq,
            "head_hash": head_hash,
            "previous_checkpoint_sha256": previous_hash,
            "checkpoint_sha256": checkpoint_sha256(checkpoint),
            "signer_key_id": key_id,
        }
    except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error, InvalidSignature):
        return blocked


def verify_checkpoint_chain(checkpoints: Sequence[Mapping], *, trusted_signer_sha256: str) -> dict:
    if not isinstance(checkpoints, Sequence) or isinstance(checkpoints, (str, bytes)) or not checkpoints:
        return {"status": "BLOCKED", "reason": "checkpoint_history_empty"}
    previous_hash = GENESIS_HASH
    previous_seq = -1
    tenant_id = None
    for checkpoint in checkpoints:
        result = verify_signed_checkpoint(
            checkpoint, trusted_signer_sha256=trusted_signer_sha256
        )
        if result["status"] != "VERIFIED":
            return result
        if tenant_id is None:
            tenant_id = result["tenant_id"]
        if result["tenant_id"] != tenant_id:
            return {"status": "BLOCKED", "reason": "checkpoint_tenant_mismatch"}
        if result["previous_checkpoint_sha256"] != previous_hash:
            return {"status": "BLOCKED", "reason": "checkpoint_link_mismatch"}
        if result["seq"] <= previous_seq:
            return {"status": "BLOCKED", "reason": "checkpoint_sequence_not_advanced"}
        previous_hash = result["checkpoint_sha256"]
        previous_seq = result["seq"]
    return {
        "status": "VERIFIED",
        "tenant_id": tenant_id,
        "seq": previous_seq,
        "checkpoint_sha256": previous_hash,
    }


def verify_firewall_evidence(
    records: Sequence[Mapping],
    checkpoint: Mapping,
    *,
    trusted_signer_sha256: str,
    checkpoint_history: Sequence[Mapping] | None = None,
) -> dict:
    chain = verify_evidence_chain(records)
    if chain["status"] != "VERIFIED":
        return chain
    signed = verify_signed_checkpoint(
        checkpoint, trusted_signer_sha256=trusted_signer_sha256
    )
    if signed["status"] != "VERIFIED":
        return signed
    if signed["tenant_id"] != chain["tenant_id"]:
        return {"status": "BLOCKED", "reason": "checkpoint_tenant_mismatch"}
    if checkpoint_history is not None:
        history_result = verify_checkpoint_chain(
            checkpoint_history, trusted_signer_sha256=trusted_signer_sha256
        )
        if history_result["status"] != "VERIFIED":
            return history_result
        if history_result["checkpoint_sha256"] != signed["checkpoint_sha256"]:
            return {"status": "BLOCKED", "reason": "checkpoint_history_tip_mismatch"}
    seq = signed["seq"]
    if seq >= len(records):
        return {"status": "BLOCKED", "reason": "checkpoint_ahead_of_ledger"}
    if records[seq]["record_hash"] != signed["head_hash"]:
        return {"status": "BLOCKED", "reason": "checkpoint_head_mismatch"}
    return {
        "status": "VERIFIED",
        "scope": "ledger_integrity_and_checkpoint_signature",
        "tenant_id": signed["tenant_id"],
        "checkpoint_seq": seq,
        "checkpoint_head_hash": signed["head_hash"],
        "ledger_tip_seq": chain["seq"],
        "ledger_tip_hash": chain["head_hash"],
        "not_established": [
            "semantic_correctness_of_execution",
            "host_integrity_beyond_the_pinned_target_helper",
            "operator_human_identity_beyond_credential_separation",
        ],
    }
