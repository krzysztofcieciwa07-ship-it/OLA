"""Trust boundary to independent Vantage AFE service.

This is a *guarded local pilot*. The Vantage classifier is heuristic.
A verified signature authenticates the signer and exact policy message, NOT
production authorization, independent binary provenance or model robustness.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


RECEIPT_FIELDS = frozenset({
    "schema", "operation_id", "tenant_id", "action", "task_sha256",
    "verdict", "detector_score", "incident_score", "sandbox_stability",
    "classifier", "source_commit", "issued_at", "expires_at",
    "request_nonce", "signer_key_id", "trust_scope", "production_authorized",
})
HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX_PUBLIC = re.compile(r"[0-9a-fA-F]{64}\Z")
HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
NONCE = re.compile(r"[a-f0-9]{32}\Z")


class VantagePolicyError(RuntimeError):
    """Fail-closed policy verification. Never contain credentials in the message."""


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _pinned_key():
    raw = os.getenv("OLA_VANTAGE_ED25519_PUBLIC_KEY_HEX", "")
    if not HEX_PUBLIC.fullmatch(raw):
        raise VantagePolicyError("Vantage trusted public key missing")
    public_raw = bytes.fromhex(raw)
    return Ed25519PublicKey.from_public_bytes(public_raw), (
        "vantage-ed25519-sha256-" + hashlib.sha256(public_raw).hexdigest()[:32]
    )


def verify_signed_envelope(envelope, *, tenant_id, operation_id, action,
                           task_sha256, request_nonce, expected_commit, now=None):
    now = int(time.time()) if now is None else int(now)
    key, key_id = _pinned_key()
    if not isinstance(envelope, dict) or set(envelope) != {"receipt", "signature"}:
        raise VantagePolicyError("Vantage envelope malformed")
    r = envelope["receipt"]
    if not isinstance(r, dict) or set(r) != RECEIPT_FIELDS:
        raise VantagePolicyError("Vantage receipt missing or extra fields")
    signature_text = envelope["signature"]
    if not isinstance(signature_text, str):
        raise VantagePolicyError("Vantage signature missing")
    try:
        raw_signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VantagePolicyError("Vantage signature is invalid") from exc
    if len(raw_signature) != 64:
        raise VantagePolicyError("Vantage Ed25519 signature length invalid")
    try:
        key.verify(raw_signature, canonical_json(r).encode("utf-8"))
    except InvalidSignature as exc:
        raise VantagePolicyError("Vantage signature did not verify") from exc

    if (r.get("schema") != "ola.vantage.receipt.v1"
            or r.get("tenant_id") != tenant_id
            or r.get("operation_id") != operation_id
            or r.get("action") != action
            or r.get("task_sha256") != task_sha256
            or r.get("request_nonce") != request_nonce
            or r.get("signer_key_id") != key_id
            or r.get("source_commit") != expected_commit
            or r.get("classifier") != "vantage.AFE"
            or r.get("trust_scope") != "signed_heuristic_policy_only"
            or r.get("production_authorized") is not False
            or r.get("verdict") not in ("ALLOW", "BLOCK", "HUMAN_APPROVAL")):
        raise VantagePolicyError("Vantage decision scope or source identity mismatch")
    if (type(r.get("issued_at")) is not int or type(r.get("expires_at")) is not int
            or r["issued_at"] > now + 5
            or r["issued_at"] < now - 30
            or r["expires_at"] <= now
            or r["expires_at"] - r["issued_at"] > 30):
        raise VantagePolicyError("Vantage decision is expired or outside bounded clock skew")
    for field in ("detector_score", "incident_score", "sandbox_stability"):
        if type(r.get(field)) is not int or not 0 <= r[field] <= 100:
            raise VantagePolicyError("Vantage numeric risk field malformed")
    return r


def request_verified_vantage_decision(*, tenant_id, operation_id, action, task_text):
    if action != "safe_expression":
        raise VantagePolicyError("Vantage action is not allowlisted for this pilot")
    url = os.getenv("VANTAGE_POLICY_URL", "").strip()
    endpoint = urlsplit(url)
    if (endpoint.scheme not in ("http", "https")
            or not endpoint.hostname
            or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment
            or endpoint.path != "/v1/decisions"):
        raise VantagePolicyError("Vantage endpoint not configured")
    if endpoint.scheme == "http" and endpoint.hostname not in (
            "127.0.0.1", "localhost", "vantage"):
        raise VantagePolicyError("plain HTTP to non-loopback/non-private Vantage denied")
    shared = os.getenv("OLA_VANTAGE_HMAC_SECRET", "").encode("utf-8")
    if len(shared) < 32:
        raise VantagePolicyError("Vantage HMAC credential is missing")
    expected = os.getenv("OLA_VANTAGE_EXPECTED_SOURCE_COMMIT", "")
    if not HEX_SHA.fullmatch(expected):
        raise VantagePolicyError("Vantage source commit not pinned")
    if not isinstance(task_text, str) or not 1 <= len(task_text) <= 2000:
        raise VantagePolicyError("Vantage task input outside bounds")

    digest = hashlib.sha256(task_text.encode("utf-8")).hexdigest()
    request = {
        "schema": "ola.vantage.request.v1",
        "operation_id": operation_id,
        "tenant_id": tenant_id,
        "action": action,
        "task_sha256": digest,
        "task_text": task_text,
    }
    raw = canonical_json(request).encode("utf-8")
    now = int(time.time())
    nonce = secrets.token_hex(16)
    mac = hmac.new(shared, f"v1\n{now}\n{nonce}\n{hashlib.sha256(raw).hexdigest()}".encode(),
                   hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-OLA-Timestamp": str(now),
        "X-OLA-Nonce": nonce,
        "X-OLA-Signature": mac,
    }
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = client.post(url, content=raw, headers=headers)
            if response.status_code != 200:
                raise VantagePolicyError("Vantage policy refused or unavailable")
            if len(response.content) > 16384:
                raise VantagePolicyError("Vantage response exceeded size bound")
            envelope = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise VantagePolicyError("Vantage network or payload verification failed") from exc

    verify_signed_envelope(
        envelope, tenant_id=tenant_id, operation_id=operation_id,
        action=action, task_sha256=digest, request_nonce=nonce,
        expected_commit=expected, now=int(time.time()),
    )
    return envelope
