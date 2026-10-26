"""Signed Stripe webhook contract; all Stripe and agent interactions stay local."""

import hashlib
import hmac
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import stripe_webhook
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import EvidenceRecord, StripeCheckoutClaim, StripeEvent, Tenant


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
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))
    event_id, payload, signature = _signed_event(tenant_id)
    first = _post_webhook(payload, signature)
    second = _post_webhook(payload, signature)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert first.json()["payment"] == "CONFIRMED"
    assert first.json()["ola_run_id"] is None
    assert calls == []
    records = _records_for(tenant_id)
    assert [r.record_type for r in records] == [
        "stripe.payment_confirmed", "stripe.fulfillment_held",
    ]
    assert verify_chain([{
        "tenant_id": r.tenant_id, "seq": r.seq, "prev_hash": r.prev_hash,
        "record_type": r.record_type, "record_hash": r.record_hash,
        "payload_json": r.payload_json,
    } for r in records])[0]
    with SessionLocal() as db:
        persisted = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert persisted.status == "PENDING_HUMAN_AUTHORIZATION"
        assert json.loads(persisted.result_json)["status"] == persisted.status


def test_signed_payment_with_blocked_agent_never_completes(tenant_id, monkeypatch):
    # Payment is not proof of agent authorization, regardless of mocked result.
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: (
        calls.append(True) or {"status": "BLOCK", "run_id": "blocked"}))
    event_id, payload, signature = _signed_event(tenant_id)
    response = _post_webhook(payload, signature)
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert response.json()["ola_run_id"] is None
    assert calls == []
    with SessionLocal() as db:
        persisted = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert persisted.status == "PENDING_HUMAN_AUTHORIZATION"


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
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))
    event_id, payload, signature = _signed_event(tenant_id)
    response = _post_webhook(payload, signature)
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert response.json()["ola_status"] == "NOT_EXECUTED"
    assert calls == []
    with SessionLocal() as db:
        recorded = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert recorded.status == "PENDING_HUMAN_AUTHORIZATION"
    assert [r.record_type for r in _records_for(tenant_id)] == [
        "stripe.payment_confirmed", "stripe.fulfillment_held",
    ]


def test_two_stripe_events_for_one_checkout_execute_only_once(tenant_id, monkeypatch):
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))
    checkout_id = "cs_test_" + uuid.uuid4().hex
    first_id, first_payload, first_sig = _signed_event(
        tenant_id, session_overrides={"id": checkout_id})
    second_id, second_payload, second_sig = _signed_event(
        tenant_id, session_overrides={"id": checkout_id})
    assert first_id != second_id
    first = _post_webhook(first_payload, first_sig)
    second = _post_webhook(second_payload, second_sig)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert calls == []
    assert len(_records_for(tenant_id)) == 2


def test_concurrent_distinct_events_for_one_checkout_do_not_both_run(tenant_id, monkeypatch):
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))
    checkout_id = "cs_test_" + uuid.uuid4().hex
    _, first_payload, first_sig = _signed_event(
        tenant_id, session_overrides={"id": checkout_id})
    _, second_payload, second_sig = _signed_event(
        tenant_id, session_overrides={"id": checkout_id})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda args: _post_webhook(*args),
                                  [(first_payload, first_sig), (second_payload, second_sig)]))
    # A concurrent claim may be locked during processing (409), or return
    # the same durable hold (200). Neither outcome is permission to execute.
    assert all(resp.status_code in {200, 409} for resp in responses)
    assert any(resp.status_code == 200 for resp in responses)
    for resp in responses:
        if resp.status_code == 200:
            assert resp.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert calls == []
    assert len(_records_for(tenant_id)) == 2


def test_legacy_checkout_without_unique_claim_requires_reconciliation(tenant_id, monkeypatch):
    checkout_id = "cs_test_" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(StripeEvent(
            id=str(uuid.uuid4()), event_id="evt_legacy_" + uuid.uuid4().hex,
            status="PENDING_INDEPENDENT_VERIFICATION", task="Audit this workflow",
            result_json=json.dumps({"status": "PENDING_INDEPENDENT_VERIFICATION",
                                    "checkout_session_id": checkout_id}),
        ))
        db.commit()
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))
    _, payload, signature = _signed_event(tenant_id, session_overrides={"id": checkout_id})
    response = _post_webhook(payload, signature)
    assert response.status_code == 409
    assert calls == []


def test_reused_checkout_with_conflicting_tenant_is_denied(tenant_id, monkeypatch):
    other_tenant = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=other_tenant, name="other-tenant-replay-test"))
        db.commit()
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))
    checkout_id = "cs_test_" + uuid.uuid4().hex
    _, payload, signature = _signed_event(tenant_id, session_overrides={"id": checkout_id})
    assert _post_webhook(payload, signature).status_code == 200
    _, other_payload, other_sig = _signed_event(
        other_tenant, session_overrides={"id": checkout_id})
    conflict = _post_webhook(other_payload, other_sig)
    assert conflict.status_code == 409
    assert calls == []
    with SessionLocal() as db:
        claim = db.get(StripeCheckoutClaim, checkout_id)
        assert claim.tenant_id == tenant_id


def test_evidence_failure_stops_runtime_and_marks_checkout_for_reconciliation(
    tenant_id, monkeypatch,
):
    calls = []
    monkeypatch.setattr(stripe_webhook, "run_agent_task", lambda *_: calls.append(True))

    def fail_evidence(*_args):
        raise RuntimeError("evidence write unavailable")

    monkeypatch.setattr(stripe_webhook, "_append_evidence", fail_evidence)
    event_id, payload, signature = _signed_event(tenant_id)
    session_id = json.loads(payload)["data"]["object"]["id"]
    with pytest.raises(RuntimeError, match="evidence write unavailable"):
        _post_webhook(payload, signature)
    assert calls == []
    with SessionLocal() as db:
        claim = db.get(StripeCheckoutClaim, session_id)
        event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert claim.status == event.status == "FAILED"


def test_failed_runtime_cannot_auto_retry_via_new_stripe_event(tenant_id, monkeypatch):
    # A runtime that would crash is never invoked solely by Stripe.
    calls = []
    def forbidden_runtime(*_args):
        calls.append(True)
        raise RuntimeError("unauthorized runtime was invoked")
    monkeypatch.setattr(stripe_webhook, "run_agent_task", forbidden_runtime)
    session_id = "cs_test_" + uuid.uuid4().hex
    _, first_payload, first_sig = _signed_event(
        tenant_id, session_overrides={"id": session_id})
    _, second_payload, second_sig = _signed_event(
        tenant_id, session_overrides={"id": session_id})
    first = _post_webhook(first_payload, first_sig)
    second = _post_webhook(second_payload, second_sig)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls == []
    with SessionLocal() as db:
        assert db.get(StripeCheckoutClaim, session_id).status == "PENDING_HUMAN_AUTHORIZATION"


