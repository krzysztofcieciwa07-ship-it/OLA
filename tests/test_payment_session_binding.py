"""Regression: paid Checkout sessions are tenant-authenticated status only."""
import json
import uuid

from fastapi.testclient import TestClient

from app import main
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.models import ApiKey, StripeCheckoutClaim, StripeEvent, Tenant


def _owner():
    tenant_id = str(uuid.uuid4())
    raw_key = "status-test-" + tenant_id
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="session-binding-test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(raw_key)))
        db.commit()
    return tenant_id, raw_key


def record_completed_checkout(tenant_id, task, checkout_id, run_id, *, status):
    event_id = "evt_" + uuid.uuid4().hex
    with SessionLocal() as db:
        result = json.dumps({
            "status": "COMPLETED", "checkout_session_id": checkout_id,
            "event_id": event_id, "ola_run_id": run_id,
            "ola_final_result": "CONFIDENTIAL_REPORT",
        })
        db.add(StripeEvent(
            id=str(uuid.uuid4()), event_id=event_id,
            status=status, task=task, run_id=run_id, result_json=result,
        ))
        db.add(StripeCheckoutClaim(
            session_id=checkout_id, tenant_id=tenant_id, event_id=event_id,
            task=task, status=status, result_json=result,
        ))
        db.commit()


def paid_session(checkout_id, task, tenant):
    return {
        "id": checkout_id, "payment_status": "paid", "status": "complete",
        "metadata": {
            "product": "OLA Execution Audit", "offer": "ola-execution-audit",
            "tenant_id": tenant, "task": task,
        },
    }


def test_payment_success_binds_result_to_exact_checkout_session(monkeypatch):
    tenant_id, raw_key = _owner()
    task = "same audit request " + str(uuid.uuid4())
    first_id, second_id = "cs_test_" + uuid.uuid4().hex, "cs_test_" + uuid.uuid4().hex
    record_completed_checkout(tenant_id, task, first_id, "run_first", status="PENDING_INDEPENDENT_VERIFICATION")
    record_completed_checkout(tenant_id, task, second_id, "run_second", status="DELIVERY_RESERVED")
    monkeypatch.setattr(main, "retrieve_checkout",
                        lambda sid: paid_session(sid, task, tenant_id))
    result = TestClient(main.app).get(
        "/payment-success", params={"session_id": second_id},
        headers={"X-API-Key": raw_key},
    )
    assert result.status_code == 200
    assert result.json() == {"status": "DELIVERY_RESERVED", "session_id": second_id}
    assert "run_first" not in result.text
    assert "run_second" not in result.text
    assert "CONFIDENTIAL_REPORT" not in result.text
    assert "task" not in result.json()


def test_payment_success_does_not_disclose_other_session_result(monkeypatch):
    tenant_id, raw_key = _owner()
    task = "same audit request " + str(uuid.uuid4())
    previous_id = "cs_test_" + uuid.uuid4().hex
    unknown_id = "cs_test_" + uuid.uuid4().hex
    record_completed_checkout(tenant_id, task, previous_id, "run_other",
                              status="PENDING_INDEPENDENT_VERIFICATION")
    calls = []
    monkeypatch.setattr(main, "retrieve_checkout",
                        lambda sid: calls.append(sid) or paid_session(sid, task, tenant_id))
    result = TestClient(main.app).get(
        "/payment-success", params={"session_id": unknown_id},
        headers={"X-API-Key": raw_key},
    )
    assert result.status_code == 404
    assert calls == []  # no remote Stripe lookup for an unowned/unknown order
    assert "run_other" not in result.text


def test_legacy_completed_does_not_claim_customer_delivery(monkeypatch):
    tenant_id, raw_key = _owner()
    task = "legacy task " + str(uuid.uuid4())
    session_id = "cs_test_" + uuid.uuid4().hex
    record_completed_checkout(tenant_id, task, session_id, "historic_run",
                              status="COMPLETED")
    monkeypatch.setattr(main, "retrieve_checkout",
                        lambda _: paid_session(session_id, task, tenant_id))
    result = TestClient(main.app).get(
        "/payment-success", params={"session_id": session_id},
        headers={"X-API-Key": raw_key},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "RECONCILIATION_REQUIRED"
    assert "historic_run" not in result.text
    assert "CONFIDENTIAL_REPORT" not in result.text
