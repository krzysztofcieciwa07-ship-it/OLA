import hashlib
import hmac
import json
import time
import uuid

import pytest

import app.main as main_module
import app.stripe_webhook as stripe_module
from app.database import SessionLocal
from app.models import StripeEvent
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


@pytest.mark.parametrize("runtime_status", ["VERIFIED", "BLOCK"])
def test_paid_audit_preserves_truth_and_does_not_complete_blocked_execution(
        monkeypatch, runtime_status):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(stripe_module, "_append_evidence", lambda *_args: str(uuid.uuid4()))
    truth = {"answer_correctness": "UNKNOWN", "independent_fact_checks": 0,
             "real_llm_invocations": 0, "execution_mode": "DETERMINISTIC_SIMULATION"}
    monkeypatch.setattr(stripe_module, "run_agent_task", lambda *_args: {
        "run_id": str(uuid.uuid4()), "status": runtime_status,
        "final_result": "unverified estimate", "evidence_ids": [], "truth": truth,
    })
    checkout_id = "cs_" + uuid.uuid4().hex
    event = {"id": "evt_" + uuid.uuid4().hex, "type": "checkout.session.completed",
             "data": {"object": {**_paid_session(), "id": checkout_id}}}
    raw = json.dumps(event).encode()
    now = int(time.time())
    signature = hmac.new(SECRET.encode(), f"{now}.".encode() + raw, hashlib.sha256).hexdigest()
    signed = f"t={now},v1={signature}"

    result = stripe_module.process_checkout_event(raw, signed)
    expected = "COMPLETED" if runtime_status == "VERIFIED" else "EXECUTION_BLOCKED"
    assert result["status"] == expected
    assert result["payment"] == "CONFIRMED"
    assert result["ola_truth"] == truth
    assert result["production_decision"] == "NO_GO"
    with SessionLocal() as db:
        recorded = db.query(StripeEvent).filter_by(event_id=event["id"]).one()
        assert recorded.status == expected

    assert stripe_module.process_checkout_event(raw, signed) == result  # idempotency
    monkeypatch.setattr(main_module, "retrieve_checkout", lambda _session_id: {
        **_paid_session(), "id": checkout_id,
    })
    monkeypatch.setattr(main_module, "payment_verified", lambda _session: True)
    success = main_module.payment_success(checkout_id)
    assert success["status"] == expected
    assert success["result"]["ola_truth"] == truth
