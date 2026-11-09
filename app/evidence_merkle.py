"""Tenant-scoped Merkle checkpoints layered on top of OLA Evidence Chain.

A checkpoint is created only after verifying the complete tenant chain from
GENESIS_HASH. Merkle leaves bind tenant, sequence, record type, and the
already-verified Evidence Chain record hash. This module does not mutate the
append-only evidence table and does not make a self-published key trusted.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .hashchain import GENESIS_HASH, canonical_json, verify_chain

CHECKPOINT_SCHEMA = "ola.evidence.merkle-checkpoint/v0.1"
MERKLE_ALGORITHM = "sha256-ola-domain-separated-v1"
_MERKLE_SPEC = {
    "algorithm": "sha256",
    "leaf_prefix": "00",
    "node_prefix": "01",
    "odd_leaf": "duplicate-last",
}
_RECORD_FIELDS = (
    "tenant_id", "seq", "prev_hash", "record_hash", "record_type", "payload_json",
)


class EvidenceCheckpointError(ValueError):
    """Raised when evidence cannot be safely checkpointed."""


def _require_sha256_hex(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise EvidenceCheckpointError(f"{field} must be a 64-character SHA-256 hex digest")
    if any(char not in "0123456789abcdef" for char in value):
        raise EvidenceCheckpointError(f"{field} must use lowercase SHA-256 hex")
    return value


def _normalize_and_verify_chain(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise EvidenceCheckpointError("records must be a sequence of evidence record mappings")
    if not records:
        raise EvidenceCheckpointError("cannot checkpoint an empty evidence chain")

    normalized: list[dict[str, Any]] = []
    expected_tenant: str | None = None
    for index, item in enumerate(records):
        if not isinstance(item, Mapping):
            raise EvidenceCheckpointError(f"record {index} must be a mapping")
        missing = [field for field in _RECORD_FIELDS if field not in item]
        if missing:
            raise EvidenceCheckpointError(
                f"record {index} is missing required fields: {', '.join(missing)}"
            )

        tenant_id = item["tenant_id"]
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise EvidenceCheckpointError(f"record {index} has an invalid tenant_id")
        if expected_tenant is None:
            expected_tenant = tenant_id
        elif tenant_id != expected_tenant:
            raise EvidenceCheckpointError("a checkpoint may contain only one tenant")

        seq = item["seq"]
        if type(seq) is not int or seq != index:
            raise EvidenceCheckpointError(
                "v0.1 checkpoints require the complete tenant chain starting at sequence 0"
            )
        record_type = item["record_type"]
        if not isinstance(record_type, str) or not record_type.strip():
            raise EvidenceCheckpointError(f"record {index} has an invalid record_type")
        payload_json = item["payload_json"]
        if not isinstance(payload_json, str):
            raise EvidenceCheckpointError(f"record {index} payload_json must be text")

        normalized.append({
            "tenant_id": tenant_id,
            "seq": seq,
            "prev_hash": _require_sha256_hex(item["prev_hash"], f"record[{index}].prev_hash"),
            "record_hash": _require_sha256_hex(item["record_hash"], f"record[{index}].record_hash"),
            "record_type": record_type,
            "payload_json": payload_json,
        })

    if normalized[0]["prev_hash"] != GENESIS_HASH:
        raise EvidenceCheckpointError("the first evidence record does not reference GENESIS_HASH")

    valid, reason = verify_chain(normalized)
    if not valid:
        raise EvidenceCheckpointError(f"evidence chain failed verification: {reason}")
    return normalized


def _leaf_digest(record: Mapping[str, Any]) -> str:
    material = canonical_json({
        "tenant_id": record["tenant_id"],
        "seq": record["seq"],
        "record_type": record["record_type"],
        "record_hash": record["record_hash"],
    }).encode("utf-8")
    return hashlib.sha256(b"\x00" + material).hexdigest()


def _node_digest(left_hex: str, right_hex: str) -> str:
    left = bytes.fromhex(_require_sha256_hex(left_hex, "left Merkle node"))
    right = bytes.fromhex(_require_sha256_hex(right_hex, "right Merkle node"))
    return hashlib.sha256(b"\x01" + left + right).hexdigest()


def _merkle_levels(leaves: Sequence[str]) -> list[list[str]]:
    if not leaves:
        raise EvidenceCheckpointError("Merkle tree requires at least one leaf")
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        current = levels[-1]
        parents: list[str] = []
        for offset in range(0, len(current), 2):
            left = current[offset]
            right = current[offset + 1] if offset + 1 < len(current) else left
            parents.append(_node_digest(left, right))
        levels.append(parents)
    return levels


def _normalize_timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if not isinstance(value, str) or not value:
        raise EvidenceCheckpointError("created_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceCheckpointError("created_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceCheckpointError("created_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return canonical_json(dict(manifest)).encode("utf-8")


def create_checkpoint(
    records: Sequence[Mapping[str, Any]],
    *,
    signing_key: Any,
    signer_key_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Verify a full tenant chain and return a signed Ed25519 Merkle checkpoint.

    signing_key must provide the Ed25519 private-key interface (sign/public_key).
    Private-key storage and signer authorization remain the caller's responsibility.
    """
    normalized = _normalize_and_verify_chain(records)
    if not isinstance(signer_key_id, str) or not signer_key_id.strip() or len(signer_key_id) > 128:
        raise EvidenceCheckpointError("signer_key_id must be a non-empty string of at most 128 characters")
    sign = getattr(signing_key, "sign", None)
    public_key_method = getattr(signing_key, "public_key", None)
    if not callable(sign) or not callable(public_key_method):
        raise EvidenceCheckpointError("signing_key must expose sign() and public_key()")

    try:
        public_key = public_key_method()
        public_raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    except Exception as exc:
        raise EvidenceCheckpointError("signing_key must expose an Ed25519 public key") from exc
    if len(public_raw) != 32:
        raise EvidenceCheckpointError("Ed25519 public key must contain exactly 32 bytes")

    leaves = [_leaf_digest(record) for record in normalized]
    root = _merkle_levels(leaves)[-1][0]
    tenant_id = normalized[0]["tenant_id"]
    manifest = {
        "schema_version": CHECKPOINT_SCHEMA,
        "hash_chain_verifier": "app.hashchain.verify_chain",
        "tenant_id": tenant_id,
        "chain_start_seq": 0,
        "chain_end_seq": normalized[-1]["seq"],
        "chain_start_prev_hash": GENESIS_HASH,
        "chain_tip_hash": normalized[-1]["record_hash"],
        "record_count": len(normalized),
        "merkle_algorithm": MERKLE_ALGORITHM,
        "merkle_spec": dict(_MERKLE_SPEC),
        "merkle_root": root,
        "signer_key_id": signer_key_id,
        "signer_public_key_sha256": hashlib.sha256(public_raw).hexdigest(),
        "created_at": _normalize_timestamp(created_at),
    }
    signed_bytes = _manifest_bytes(manifest)
    manifest_sha256 = hashlib.sha256(signed_bytes).hexdigest()
    try:
        signature = sign(signed_bytes)
    except Exception as exc:
        raise EvidenceCheckpointError("Ed25519 signing operation failed") from exc
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise EvidenceCheckpointError("Ed25519 signature must contain exactly 64 bytes")

    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha256,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": signer_key_id,
            "public_key_raw_b64": base64.b64encode(public_raw).decode("ascii"),
            "public_key_sha256": manifest["signer_public_key_sha256"],
            "value_b64": base64.b64encode(signature).decode("ascii"),
        },
    }


def verify_checkpoint_signature(
    checkpoint: Mapping[str, Any],
    *,
    trusted_signer_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the envelope signature; trust is true only for an explicitly pinned key."""
    invalid = {
        "signature_valid": False,
        "signer_trusted": False,
        "signer_key_id": None,
        "signer_sha256": None,
        "reason": "invalid checkpoint envelope or signature",
    }
    try:
        manifest = checkpoint["manifest"]
        signature_envelope = checkpoint["signature"]
        if not isinstance(manifest, Mapping) or not isinstance(signature_envelope, Mapping):
            return invalid
        if manifest.get("schema_version") != CHECKPOINT_SCHEMA:
            return invalid
        if manifest.get("merkle_algorithm") != MERKLE_ALGORITHM:
            return invalid
        if manifest.get("merkle_spec") != _MERKLE_SPEC:
            return invalid
        tenant_id = manifest.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            return invalid
        count = manifest.get("record_count")
        if type(count) is not int or count < 1:
            return invalid
        chain_start_seq = manifest.get("chain_start_seq")
        chain_end_seq = manifest.get("chain_end_seq")
        # bool is a subclass of int in Python; reject it explicitly in signed schemas.
        if type(chain_start_seq) is not int or chain_start_seq != 0:
            return invalid
        if type(chain_end_seq) is not int or chain_end_seq != count - 1:
            return invalid
        if manifest.get("chain_start_prev_hash") != GENESIS_HASH:
            return invalid
        _require_sha256_hex(manifest.get("chain_tip_hash"), "chain_tip_hash")
        _require_sha256_hex(manifest.get("merkle_root"), "merkle_root")
        key_id = manifest.get("signer_key_id")
        if not isinstance(key_id, str) or not key_id.strip():
            return invalid
        if signature_envelope.get("algorithm") != "Ed25519" or signature_envelope.get("key_id") != key_id:
            return invalid

        public_raw = base64.b64decode(signature_envelope["public_key_raw_b64"], validate=True)
        signature = base64.b64decode(signature_envelope["value_b64"], validate=True)
        if len(public_raw) != 32 or len(signature) != 64:
            return invalid
        signer_sha256 = hashlib.sha256(public_raw).hexdigest()
        expected_manifest_fingerprint = _require_sha256_hex(
            manifest.get("signer_public_key_sha256"), "signer_public_key_sha256"
        )
        envelope_fingerprint = _require_sha256_hex(
            signature_envelope.get("public_key_sha256"), "signature.public_key_sha256"
        )
        if not hmac.compare_digest(signer_sha256, expected_manifest_fingerprint):
            return invalid
        if not hmac.compare_digest(signer_sha256, envelope_fingerprint):
            return invalid

        signed_bytes = _manifest_bytes(manifest)
        calculated_manifest_sha256 = hashlib.sha256(signed_bytes).hexdigest()
        supplied_manifest_sha256 = _require_sha256_hex(
            checkpoint.get("manifest_sha256"), "manifest_sha256"
        )
        if not hmac.compare_digest(calculated_manifest_sha256, supplied_manifest_sha256):
            return invalid
        public_key = Ed25519PublicKey.from_public_bytes(public_raw)
        public_key.verify(signature, signed_bytes)

        signer_trusted = False
        if trusted_signer_sha256 is not None:
            pinned = _require_sha256_hex(trusted_signer_sha256, "trusted_signer_sha256")
            signer_trusted = hmac.compare_digest(signer_sha256, pinned)
        return {
            "signature_valid": True,
            "signer_trusted": signer_trusted,
            "signer_key_id": key_id,
            "signer_sha256": signer_sha256,
            "reason": None,
        }
    except (KeyError, TypeError, ValueError, binascii.Error, InvalidSignature):
        return invalid


def build_inclusion_proof(
    records: Sequence[Mapping[str, Any]],
    leaf_index: int,
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a proof only when the supplied checkpoint describes this verified chain."""
    normalized = _normalize_and_verify_chain(records)
    signature_status = verify_checkpoint_signature(checkpoint)
    if not signature_status["signature_valid"]:
        raise EvidenceCheckpointError("checkpoint signature is invalid")
    if type(leaf_index) is not int or not 0 <= leaf_index < len(normalized):
        raise EvidenceCheckpointError("leaf_index is outside the evidence chain")

    manifest = checkpoint["manifest"]
    leaves = [_leaf_digest(record) for record in normalized]
    levels = _merkle_levels(leaves)
    if (
        manifest.get("tenant_id") != normalized[0]["tenant_id"]
        or manifest.get("record_count") != len(normalized)
        or manifest.get("chain_tip_hash") != normalized[-1]["record_hash"]
        or manifest.get("merkle_root") != levels[-1][0]
    ):
        raise EvidenceCheckpointError("checkpoint does not describe the supplied evidence chain")

    siblings: list[str] = []
    index = leaf_index
    for level in levels[:-1]:
        if index % 2:
            sibling = level[index - 1]
        else:
            sibling = level[index + 1] if index + 1 < len(level) else level[index]
        siblings.append(sibling)
        index //= 2

    record = normalized[leaf_index]
    proof = {
        "schema_version": CHECKPOINT_SCHEMA,
        "checkpoint_manifest_sha256": checkpoint["manifest_sha256"],
        "tenant_id": record["tenant_id"],
        "seq": record["seq"],
        "record_type": record["record_type"],
        "record_hash": record["record_hash"],
        "leaf_index": leaf_index,
        "tree_size": len(normalized),
        "siblings": siblings,
    }
    if not verify_inclusion_proof(checkpoint, proof):
        raise EvidenceCheckpointError("generated Merkle inclusion proof did not verify")
    return proof


def verify_inclusion_proof(
    checkpoint: Mapping[str, Any],
    proof: Mapping[str, Any],
    *,
    trusted_signer_sha256: str | None = None,
    require_trusted_signer: bool = False,
) -> bool:
    """Verify membership against a signed root; optionally require a pinned signer key."""
    try:
        signature_status = verify_checkpoint_signature(
            checkpoint, trusted_signer_sha256=trusted_signer_sha256
        )
        if not signature_status["signature_valid"]:
            return False
        if require_trusted_signer and not signature_status["signer_trusted"]:
            return False

        manifest = checkpoint["manifest"]
        if not isinstance(proof, Mapping) or proof.get("schema_version") != CHECKPOINT_SCHEMA:
            return False
        if proof.get("checkpoint_manifest_sha256") != checkpoint.get("manifest_sha256"):
            return False
        tenant_id = proof.get("tenant_id")
        if tenant_id != manifest.get("tenant_id"):
            return False
        tree_size = proof.get("tree_size")
        leaf_index = proof.get("leaf_index")
        seq = proof.get("seq")
        if type(tree_size) is not int or tree_size != manifest.get("record_count"):
            return False
        if type(leaf_index) is not int or not 0 <= leaf_index < tree_size:
            return False
        if type(seq) is not int or seq != manifest.get("chain_start_seq", 0) + leaf_index:
            return False
        record_type = proof.get("record_type")
        if not isinstance(record_type, str) or not record_type.strip():
            return False
        record_hash = _require_sha256_hex(proof.get("record_hash"), "proof.record_hash")
        siblings = proof.get("siblings")
        if not isinstance(siblings, list):
            return False

        current = _leaf_digest({
            "tenant_id": tenant_id,
            "seq": seq,
            "record_type": record_type,
            "record_hash": record_hash,
        })
        width = tree_size
        index = leaf_index
        expected_siblings = 0
        while width > 1:
            expected_siblings += 1
            width = (width + 1) // 2
        if len(siblings) != expected_siblings:
            return False

        width = tree_size
        index = leaf_index
        for sibling_value in siblings:
            sibling = _require_sha256_hex(sibling_value, "proof sibling")
            if index % 2:
                current = _node_digest(sibling, current)
            else:
                if index + 1 >= width and not hmac.compare_digest(sibling, current):
                    return False
                current = _node_digest(current, sibling)
            index //= 2
            width = (width + 1) // 2

        return hmac.compare_digest(current, manifest["merkle_root"])
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False


def load_tenant_evidence_records(tenant_id: str) -> list[dict[str, Any]]:
    """Read one tenant's full chain in sequence order; caller must authorize tenant_id."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise EvidenceCheckpointError("tenant_id is required")

    from sqlalchemy import select

    from .database import SessionLocal
    from .models import EvidenceRecord

    with SessionLocal() as db:
        rows = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.asc())
        ).all()
        return [{
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
            "record_type": row.record_type,
            "payload_json": row.payload_json,
        } for row in rows]


def create_tenant_checkpoint(
    tenant_id: str,
    *,
    signing_key: Any,
    signer_key_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create a read-only checkpoint for an already-authorized tenant scope.

    This helper performs no authentication itself. The caller must derive tenant_id
    from authenticated server context, never from an untrusted request field.
    """
    records = load_tenant_evidence_records(tenant_id)
    return create_checkpoint(
        records,
        signing_key=signing_key,
        signer_key_id=signer_key_id,
        created_at=created_at,
    )
