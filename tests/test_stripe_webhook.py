import hashlib
import hmac
import json
import time

import pytest

from app.stripe_webhook import _validate_checkout, verify_stripe_signature


SECRET = "whsec_test_ola"
TIMESTAMP = 1_800_000_000


def _signature(payload: bytes) -> str:
    signed = f"{TIMESTAMP}.".encode() + payload
    digest = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={TIMESTAMP},v1={digest}"


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
    session = {
        "metadata": {"offer": "ola-execution-audit"},
        "payment_status": "paid",
        "amount_total": 9900,
        "currency": "eur",
        "custom_fields": [
            {
                "key": "audit_task",
                "type": "text",
                "text": {"value": "Audit this company workflow for evidence gaps."},
            }
        ],
    }
    assert _validate_checkout(session) == "Audit this company workflow for evidence gaps."


@pytest.mark.parametrize(
    "override",
    [
        {"payment_status": "unpaid"},
        {"amount_total": 9800},
        {"currency": "usd"},
        {"metadata": {"offer": "other-offer"}},
    ],
)
def test_invalid_checkout_is_rejected(override):
    session = {
        "metadata": {"offer": "ola-execution-audit"},
        "payment_status": "paid",
        "amount_total": 9900,
        "currency": "eur",
        "custom_fields": [
            {
                "key": "audit_task",
                "type": "text",
                "text": {"value": "Audit this company workflow for evidence gaps."},
            }
        ],
    }
    session.update(override)
    with pytest.raises(Exception):
        _validate_checkout(session)
