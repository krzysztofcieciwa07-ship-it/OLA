from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


ALGORITHM = "Ed25519"
SIGNATURE_FIELD = "_evidence_signature"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _raw_public_key_b64(key: Ed25519PublicKey) -> str:
    return base64.b64encode(
        key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def private_key_from_env() -> Ed25519PrivateKey:
    raw = os.getenv("OLA_ED25519_PRIVATE_KEY_B64")
    if not raw:
        raise RuntimeError("OLA_ED25519_PRIVATE_KEY_B64 is not configured")
    try:
        key_bytes = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise RuntimeError("OLA_ED25519_PRIVATE_KEY_B64 is not valid base64") from exc
    try:
        return Ed25519PrivateKey.from_private_bytes(key_bytes)
    except ValueError as exc:
        raise RuntimeError("OLA_ED25519_PRIVATE_KEY_B64 must encode exactly 32 bytes") from exc


def sign_record(tenant_id: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    envelope = {
        "schema": "ola-evidence-signature/v1",
        "tenant_id": tenant_id,
        "record_type": record_type,
        "payload": payload,
    }
    message = canonical_bytes(envelope)
    private_key = private_key_from_env()
    signature = private_key.sign(message)
    key_id = os.getenv("OLA_ED25519_KEY_ID", "ola-ed25519-default")
    return {
        "algorithm": ALGORITHM,
        "key_id": key_id,
        "public_key_b64": _raw_public_key_b64(private_key.public_key()),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
        "signed_sha256": hashlib.sha256(message).hexdigest(),
    }


def verify_record_signature(
    tenant_id: str,
    record_type: str,
    payload: dict[str, Any],
    signature: dict[str, Any],
    *,
    trusted_public_key_b64: str,
    expected_key_id: str | None = None,
) -> bool:
    if signature.get("algorithm") != ALGORITHM:
        return False
    if expected_key_id is not None and signature.get("key_id") != expected_key_id:
        return False

    envelope = {
        "schema": "ola-evidence-signature/v1",
        "tenant_id": tenant_id,
        "record_type": record_type,
        "payload": payload,
    }
    message = canonical_bytes(envelope)
    if signature.get("signed_sha256") != hashlib.sha256(message).hexdigest():
        return False

    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(trusted_public_key_b64, validate=True)
        )
        public_key.verify(
            base64.b64decode(signature["signature_b64"], validate=True),
            message,
        )
        return True
    except (ValueError, KeyError, InvalidSignature):
        return False


def sign_payload_if_configured(
    tenant_id: str,
    record_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not os.getenv("OLA_ED25519_PRIVATE_KEY_B64"):
        if os.getenv("OLA_REQUIRE_EVIDENCE_SIGNATURES") == "1":
            raise RuntimeError("evidence signatures are required but no Ed25519 private key is configured")
        return payload

    signed_payload = dict(payload)
    signed_payload[SIGNATURE_FIELD] = sign_record(
        tenant_id,
        record_type,
        payload,
    )
    return signed_payload
