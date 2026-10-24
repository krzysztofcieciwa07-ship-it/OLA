"""Signed Stripe webhook contract; all Stripe and agent interactions stay local."""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import stripe_webhook
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import EvidenceRecord, StripeEvent, Tenant


TEST_WEBHOOK_SECRET = "whsec_local_test_only"


def _signed_event(tenant_id, *, session_overrides=None, event_id=None):
    session = {
        "id": "cs_test_" + uuid.uuid4().hex,
        "status": "complete",
        "payment_status": "paid",
        "currency": "eur",
        "amount_total": 9900,
        "metadata": {
            "tenant_id": tenant_id,
            "offer": "ola-execution-audit",
            "product": "OLA Execution Audit",
            "task": "Audit this workflow",
        },
    }
    if session_overrides:
        session.update(session_overrides)
    event_id = event_id or "evt_test_" + uuid.uuid4().hex
    payload = json.dumps({
        "id": event_id, "type": "checkout.session.completed",
        "data": {"object": session},
    }, sort_keys=True).encode("utf-8")
    timestamp = int(time.time())
    signature = hmac.new(
        TEST_WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    return event_id, payload, f"t={timestamp},v1={signature}"


@pytest.fixture
def tenant_id(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="local-payment-webhook-test"))
        db.commit()
    return tenant_id


def _post_webhook(payload, signature):
    return TestClient(app).post(
        "/stripe/webhook", content=payload,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )


def _records_for(tenant_id):
    with SessionLocal() as db:
        return db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id
        ).order_by(EvidenceRecord.seq)).all()


def test_signed_paid_webhook_records_pending_once_and_preserves_chain(tenant_id, monkeypatch):
    calls = []

    def local_runtime(tenant, task):
        calls.append((tenant, task))
        return {"status": "VERIFIED", "run_id": "run-local-1",
                "evidence_ids": ["evidence-local-1"], "final_result": "draft audit"}

    monkeypatch.setattr(stripe_webhook, "run_agent_task", local_runtime)
    event_id, payload, signature = _signed_event(tenant_id)

    first = _post_webhook(payload, signature)
    second = _post_webhook(payload, signature)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "PENDING_INDEPENDENT_VERIFICATION"
    assert first.json()["payment"] == "CONFIRMED"
    assert first.json()["ola_run_id"] == "run-local-1"
    assert calls == [(tenant_id, "Audit this workflow")]

    records = _records_for(tenant_id)
    assert [r.record_type for r in records] == [
        "stripe.payment_confirmed", "stripe.ola_execution_recorded",
    ]
    assert verify_chain([{
        "tenant_id": r.tenant_id, "seq": r.seq, "prev_hash": r.prev_hash,
        "record_hash": r.record_hash, "record_type": r.record_type,
        "payload_json": r.payload_json,
    } for r in records])[0]

    with SessionLocal() as db:
        persisted = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert persisted.status == "PENDING_INDEPENDENT_VERIFICATION"
        assert json.loads(persisted.result_json)["status"] == persisted.status


def test_signed_payment_with_blocked_agent_never_completes(tenant_id, monkeypatch):
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: {
        "status": "BLOCK", "run_id": "run-blocked", "evidence_ids": [],
    })
    event_id, payload, signature = _signed_event(tenant_id)
    response = _post_webhook(payload, signature)
    assert response.status_code == 200
    assert response.json()["status"] == "BLOCKED"
    with SessionLocal() as db:
        persisted = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert persisted.status == "BLOCKED"


def test_bad_signature_blocks_payment_before_any_work(tenant_id, monkeypatch):
    invoked = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: invoked.append(True))
    event_id, payload, signature = _signed_event(tenant_id)
    response = _post_webhook(payload + b" ", signature)
    assert response.status_code == 400
    assert invoked == []
    assert _records_for(tenant_id) == []
    with SessionLocal() as db:
        assert db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id)) is None


def test_signed_payment_without_tenant_cannot_run(tenant_id, monkeypatch):
    invoked = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: invoked.append(True))
    event_id, payload, signature = _signed_event(tenant_id, session_overrides={
        "metadata": {"offer": "ola-execution-audit", "task": "audit"},
    })
    response = _post_webhook(payload, signature)
    assert response.status_code >= 400
    assert invoked == []
    with SessionLocal() as db:
        assert db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id)) is None


def test_signed_payment_without_completed_status_is_rejected(tenant_id, monkeypatch):
    invoked = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: invoked.append(True))
    _, payload, signature = _signed_event(tenant_id, session_overrides={"status": None})
    response = _post_webhook(payload, signature)
    assert response.status_code == 400
    assert invoked == []


def test_malformed_runtime_result_is_blocked_and_evidenced(tenant_id, monkeypatch):
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: None)
    event_id, payload, signature = _signed_event(tenant_id)
    response = _post_webhook(payload, signature)
    assert response.status_code == 200
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["ola_status"] == "UNKNOWN"
    with SessionLocal() as db:
        recorded = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert recorded.status == "BLOCKED"
    assert [r.record_type for r in _records_for(tenant_id)] == [
        "stripe.payment_confirmed", "stripe.ola_execution_recorded",
    ]
