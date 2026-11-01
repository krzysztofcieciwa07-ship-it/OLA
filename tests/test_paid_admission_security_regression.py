"""TDD red gates: paid event cannot authorize agent; status lookup requires identity."""
import hashlib
import hmac
import json
import time
import uuid

from fastapi.testclient import TestClient

from app import main, stripe_webhook
from app.database import SessionLocal
from app.models import Tenant


def test_paid_signed_webhook_holds_before_agent_invocation(monkeypatch):
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="admission-regression"))
        db.commit()
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_regression_only")
    calls = []
    monkeypatch.setattr(
        stripe_webhook, "run_agent_task",
        lambda *a, **k: calls.append((a, k)) or {
            "status": "VERIFIED", "run_id": "unauthorized", "evidence_ids": ["no"]
        },
    )
    event = {
        "id": "evt_" + uuid.uuid4().hex,
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_" + uuid.uuid4().hex,
            "metadata": {
                "tenant_id": tenant_id, "task": "buyer task",
                "offer": "ola-execution-audit", "product": "OLA Execution Audit",
                "human_approved": True, "risk": "LOW", "agent_id": "agent-001",
            },
            "status": "complete", "payment_status": "paid",
            "amount_total": 9900, "currency": "eur",
        }},
    }
    raw = json.dumps(event).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(b"whsec_regression_only",
                      timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    resp = TestClient(main.app).post(
        "/stripe/webhook", content=raw,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert calls == [], "a paid event must not invoke an agent"


def test_payment_success_without_identity_denies_before_stripe_lookup(monkeypatch):
    lookups = []
    monkeypatch.setattr(
        main, "retrieve_checkout",
        lambda *a: lookups.append(a) or {
            "metadata": {"tenant_id": "victim", "task": "SECRET_TASK"},
            "status": "complete", "payment_status": "paid",
        },
    )
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": "cs_test_leaked"})
    assert response.status_code == 401
    assert lookups == [], "no network call without authenticated buyer"
    assert "SECRET_TASK" not in response.text
