"""Status API must not disclose buyer tasks/results on a bare Stripe session ID."""
import uuid
from fastapi.testclient import TestClient
from app import main
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.models import Tenant, ApiKey, StripeCheckoutClaim, StripeEvent


def _order():
    owner = str(uuid.uuid4())
    other = str(uuid.uuid4())
    token_owner = "owner-key-" + owner
    token_other = "other-key-" + other
    session = "cs_test_" + uuid.uuid4().hex
    event = "evt_" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add_all([Tenant(id=owner, name="owner"), Tenant(id=other, name="other")])
        db.flush()
        db.add_all([
            ApiKey(id=str(uuid.uuid4()), tenant_id=owner,
                   key_hash=api_key_fingerprint(token_owner)),
            ApiKey(id=str(uuid.uuid4()), tenant_id=other,
                   key_hash=api_key_fingerprint(token_other)),
        ])
        db.add(StripeEvent(id=str(uuid.uuid4()), event_id=event,
                           status="PENDING_HUMAN_AUTHORIZATION", task="SECRET_TASK"))
        db.add(StripeCheckoutClaim(session_id=session, tenant_id=owner,
                                   event_id=event, task="SECRET_TASK",
                                   status="PENDING_HUMAN_AUTHORIZATION"))
        db.commit()
    return owner, other, token_owner, token_other, session


def _paid(tenant, session):
    return {"id": session, "status": "complete", "payment_status": "paid",
            "metadata": {"tenant_id": tenant, "task": "SECRET_TASK",
                         "offer": "ola-execution-audit",
                         "product": "OLA Execution Audit"}}


def test_missing_key_denied_before_any_stripe_lookup(monkeypatch):
    owner, _, _, _, session = _order()
    calls = []
    monkeypatch.setattr(main, "retrieve_checkout",
                        lambda *_: calls.append(True) or _paid(owner, session))
    response = TestClient(main.app).get("/payment-success", params={"session_id": session})
    assert response.status_code == 401
    assert "SECRET_TASK" not in response.text
    assert calls == []


def test_other_tenant_cannot_query_checkout_even_if_session_leaked(monkeypatch):
    owner, _, _, other_key, session = _order()
    calls = []
    monkeypatch.setattr(main, "retrieve_checkout",
                        lambda *_: calls.append(True) or _paid(owner, session))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": session},
        headers={"X-API-Key": other_key},
    )
    assert response.status_code == 404
    assert calls == []


def test_owner_receives_status_not_task_run_or_report(monkeypatch):
    owner, _, key, _, session = _order()
    monkeypatch.setattr(main, "retrieve_checkout", lambda *_: _paid(owner, session))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": session},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    assert response.json()["session_id"] == session
    assert "SECRET_TASK" not in response.text
    assert "task" not in response.json()
    assert "run_id" not in response.json()
    assert "result" not in response.json()


def test_stripe_metadata_tenant_mismatch_never_returns_order(monkeypatch):
    owner, other, key, _, session = _order()
    monkeypatch.setattr(main, "retrieve_checkout", lambda *_: _paid(other, session))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": session},
        headers={"X-API-Key": key},
    )
    assert response.status_code in {403, 404}
    assert "SECRET_TASK" not in response.text


def test_unpaid_checkout_never_returns_processing_or_delivery(monkeypatch):
    owner, _, key, _, session = _order()
    unpaid = _paid(owner, session)
    unpaid["payment_status"] = "unpaid"
    monkeypatch.setattr(main, "retrieve_checkout", lambda *_: unpaid)
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": session},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PAYMENT_NOT_VERIFIED"
    assert "SECRET_TASK" not in response.text


def test_absent_order_claim_rejected_without_stripe_lookup(monkeypatch):
    owner, _, key, _, _ = _order()
    never = "cs_test_unknown_" + uuid.uuid4().hex
    calls = []
    monkeypatch.setattr(main, "retrieve_checkout",
                        lambda *_: calls.append(True) or _paid(owner, never))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": never},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 404
    assert calls == []
