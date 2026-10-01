import base64
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evidence_signature import (
    SIGNATURE_FIELD,
    sign_payload_if_configured,
    verify_record_signature,
)


def test_ed25519_signature_round_trip(monkeypatch):
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes_raw()
    monkeypatch.setenv("OLA_ED25519_PRIVATE_KEY_B64", base64.b64encode(raw).decode())
    monkeypatch.setenv("OLA_ED25519_KEY_ID", "test-key-1")

    payload = {"event": "verification.passed", "value": 391}
    signed = sign_payload_if_configured("tenant-1", "test.event", payload)

    assert SIGNATURE_FIELD in signed
    signature = signed.pop(SIGNATURE_FIELD)
    trusted = base64.b64encode(key.public_key().public_bytes_raw()).decode()

    assert verify_record_signature(
        "tenant-1",
        "test.event",
        signed,
        signature,
        trusted_public_key_b64=trusted,
        expected_key_id="test-key-1",
    )


def test_tampered_payload_is_rejected(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "OLA_ED25519_PRIVATE_KEY_B64",
        base64.b64encode(key.private_bytes_raw()).decode(),
    )

    payload = {"event": "verification.passed", "value": 391}
    signed = sign_payload_if_configured("tenant-1", "test.event", payload)
    signature = signed.pop(SIGNATURE_FIELD)
    signed["value"] = 392

    trusted = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    assert not verify_record_signature(
        "tenant-1",
        "test.event",
        signed,
        signature,
        trusted_public_key_b64=trusted,
    )


def test_required_signing_fails_closed(monkeypatch):
    monkeypatch.delenv("OLA_ED25519_PRIVATE_KEY_B64", raising=False)
    monkeypatch.setenv("OLA_REQUIRE_EVIDENCE_SIGNATURES", "1")

    try:
        sign_payload_if_configured("tenant-1", "test.event", {"x": 1})
    except RuntimeError as exc:
        assert "required" in str(exc)
    else:
        raise AssertionError("missing signing key must fail closed")
