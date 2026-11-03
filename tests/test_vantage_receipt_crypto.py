"""Negative tests for independent Vantage signature and scope validation."""
import base64
import hashlib
import json
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.vantage_client import VantagePolicyError, verify_signed_envelope, canonical_json


def fixture(monkeypatch):
    key = Ed25519PrivateKey.generate()
    raw_public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    monkeypatch.setenv("OLA_VANTAGE_ED25519_PUBLIC_KEY_HEX", raw_public.hex())
    nonce = "a" * 32
    tenant, operation = str(uuid.uuid4()), str(uuid.uuid4())
    issued = int(time.time())
    receipt = {
        "schema": "ola.vantage.receipt.v1",
        "operation_id": operation,
        "tenant_id": tenant,
        "action": "safe_expression",
        "task_sha256": hashlib.sha256(b"Calculate 17 * 23").hexdigest(),
        "verdict": "ALLOW",
        "detector_score": 0,
        "incident_score": 0,
        "sandbox_stability": 95,
        "classifier": "vantage.AFE",
        "source_commit": "b" * 40,
        "issued_at": issued,
        "expires_at": issued + 30,
        "request_nonce": nonce,
        "signer_key_id": "vantage-ed25519-sha256-" + hashlib.sha256(raw_public).hexdigest()[:32],
        "trust_scope": "signed_heuristic_policy_only",
        "production_authorized": False,
    }
    original_task_hash = receipt["task_sha256"]
    def sign(r):
        return {"receipt": r, "signature": base64.b64encode(
            key.sign(canonical_json(r).encode())).decode()}
    def verify(env, **kwargs):
        return verify_signed_envelope(
            env, tenant_id=tenant, operation_id=operation,
            action="safe_expression", task_sha256=original_task_hash,
            request_nonce=nonce, expected_commit="b" * 40, now=issued,
            **kwargs,
        )
    return receipt, sign, verify


def test_real_ed25519_receipt_validates_exact_context(monkeypatch):
    receipt, sign, verify = fixture(monkeypatch)
    assert verify(sign(receipt))["verdict"] == "ALLOW"


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "00000000-0000-0000-0000-000000000000"),
    ("operation_id", "00000000-0000-0000-0000-000000000000"),
    ("action", "run_shell"),
    ("task_sha256", "0" * 64),
    ("source_commit", "c" * 40),
    ("signer_key_id", "attacker-key"),
    ("trust_scope", "production"),
    ("production_authorized", True),
])
def test_signed_but_wrong_scope_is_rejected(monkeypatch, field, value):
    receipt, sign, verify = fixture(monkeypatch)
    receipt[field] = value
    with pytest.raises(VantagePolicyError):
        verify(sign(receipt))


def test_unsigned_mutation_and_stale_receipt_rejected(monkeypatch):
    receipt, sign, verify = fixture(monkeypatch)
    env = sign(receipt)
    env["receipt"]["verdict"] = "BLOCK"
    with pytest.raises(VantagePolicyError):
        verify(env)
    receipt["expires_at"] = receipt["issued_at"] - 1
    with pytest.raises(VantagePolicyError):
        verify(sign(receipt))


def test_unknown_public_key_causes_fail_closed(monkeypatch):
    receipt, sign, verify = fixture(monkeypatch)
    monkeypatch.delenv("OLA_VANTAGE_ED25519_PUBLIC_KEY_HEX")
    with pytest.raises(VantagePolicyError):
        verify(sign(receipt))
