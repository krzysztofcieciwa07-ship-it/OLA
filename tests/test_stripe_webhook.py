import hashlib
import hmac

import pytest

from app.stripe_webhook import _validate_checkout, verify_stripe_signature


SECRET = "whsec_test_ola"
TIMESTAMP = 1_800_000_000


def _signature(payload: bytes) -> str:
    signed = f"{TIMESTAMP}.".encode() + payload
    digest = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={TIMESTAMP},v1={digest}"


def _paid_session():
    return {
        "metadata": {
            "offer": "ola-execution-audit",
            "product": "OLA Execution Audit",
            "task": "Audit this company workflow for evidence gaps.",
            "tenant_id": "tenant-test",
        },
        "payment_status": "paid",
        "status": "complete",
        "amount_total": 9900,
        "currency": "eur",
    }


def test_stripe_signature_accepts_valid_signature():
    payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
    assert verify_stripe_signature(payload, _signature(payload), SECRET, now=TIMESTAMP)


def test_stripe_signature_rejects_tampered_payload():
    payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
    signature = _signature(payload)
    tampered = b'{"id":"evt_test","type":"checkout.session.completed","x":"tampered"}'
    assert not verify_stripe_signature(tampered, signature, SECRET, now=TIMESTAMP)


def test_stripe_signature_rejects_old_timestamp():
    payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
    signature = _signature(payload)
    assert not verify_stripe_signature(payload, signature, SECRET, now=TIMESTAMP + 301)


def test_paid_ola_checkout_extracts_audit_task():
    assert _validate_checkout(_paid_session()) == "Audit this company workflow for evidence gaps."


@pytest.mark.parametrize(
    "override",
    [
        {"payment_status": "unpaid"},
        {"amount_total": 9800},
        {"currency": "usd"},
        {"metadata": {"offer": "other-offer", "product": "OLA Execution Audit", "task": "x"}},
    ],
)
def test_invalid_checkout_is_rejected(override):
    session = _paid_session()
    session.update(override)
    with pytest.raises(Exception):
        _validate_checkout(session)


def test_paid_checkout_uses_metadata_task_without_custom_fields():
    session = _paid_session()
    assert "custom_fields" not in session
    assert _validate_checkout(session) == "Audit this company workflow for evidence gaps."
