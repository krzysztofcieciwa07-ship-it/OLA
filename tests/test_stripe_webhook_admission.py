"""Regressions: a payment notification cannot authorize an AI action.

These tests intentionally fail against PR #119: a valid Stripe event currently
starts run_agent_task with no independent approval.
"""
import json
from sqlalchemy import select
from fastapi.testclient import TestClient

from app import stripe_webhook
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import StripeEvent, StripeCheckoutClaim
from tests.test_stripe_webhook_flow import (
    tenant_id, _signed_event, _records_for,
)


def test_paid_webhook_is_durable_but_never_executes_without_human_approval(
    tenant_id, monkeypatch,
):
    invocations = []
    monkeypatch.setattr(
        stripe_webhook, "run_agent_task",
        lambda *args: invocations.append(args) or {
            "status": "VERIFIED", "run_id": "unapproved-run",
            "evidence_ids": ["bad-proof"],
        },
    )
    event_id, payload, sig = _signed_event(tenant_id)
    response = TestClient(app).post(
        "/stripe/webhook", content=payload,
        headers={"Stripe-Signature": sig},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert result["payment"] == "CONFIRMED"
    assert result.get("ola_run_id") is None
    assert invocations == []

    with SessionLocal() as db:
        event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        claim = db.get(StripeCheckoutClaim, json.loads(payload)["data"]["object"]["id"])
        assert event.status == claim.status == "PENDING_HUMAN_AUTHORIZATION"
        assert event.result_json == claim.result_json
    records = _records_for(tenant_id)
    assert [r.record_type for r in records] == [
        "stripe.payment_confirmed", "stripe.fulfillment_held",
    ]
    assert verify_chain([{
        "tenant_id": r.tenant_id, "seq": r.seq, "record_type": r.record_type,
        "payload_json": r.payload_json, "prev_hash": r.prev_hash,
        "record_hash": r.record_hash,
    } for r in records]) == (True, "ok")


def test_duplicate_signed_events_do_not_bypass_human_hold(tenant_id, monkeypatch):
    invocations = []
    monkeypatch.setattr(
        stripe_webhook, "run_agent_task",
        lambda *args: invocations.append(args),
    )
    session_id = "cs_test_repeat_admission_" + "a" * 32
    _, first, sig1 = _signed_event(tenant_id, session_overrides={"id": session_id})
    _, second, sig2 = _signed_event(tenant_id, session_overrides={"id": session_id})
    client = TestClient(app)
    result1 = client.post("/stripe/webhook", content=first,
                          headers={"Stripe-Signature": sig1})
    result2 = client.post("/stripe/webhook", content=second,
                          headers={"Stripe-Signature": sig2})
    assert result1.status_code == result2.status_code == 200
    assert result1.json() == result2.json()
    assert result2.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert invocations == []
    assert len(_records_for(tenant_id)) == 2
