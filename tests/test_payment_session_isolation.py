"""Security regression tests for Stripe checkout result isolation.

A shared task description MUST NOT join results from another checkout session.
"""
import hashlib
import importlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import ApiKey, StripeEvent, Tenant

main = importlib.import_module("app.main")


def _tenant():
    tenant_id = str(uuid.uuid4())
    token = "key-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="payment-security-test"))
        db.add(ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=hashlib.sha256(token.encode()).hexdigest(),
        ))
        db.commit()
    return tenant_id, token


def _session(tenant_id, session_id, task="same task"):
    return {
        "id": session_id,
        "metadata": {
            "tenant_id": tenant_id,
            "task": task,
            "product": "OLA Execution Audit",
            "offer": "ola-execution-audit",
        },
        "payment_status": "paid",
        "status": "complete",
        "currency": "eur",
        "amount_total": 9900,
    }


def _completed(session_id, task="same task", run_id=None):
    event_id = "evt_" + uuid.uuid4().hex
    run_id = run_id or "run_" + uuid.uuid4().hex
    result = {
        "status": "COMPLETED",
        "event_id": event_id,
        "checkout_session_id": session_id,
        "payment": "CONFIRMED",
        "ola_run_id": run_id,
        "ola_final_result": {"owner": session_id},
    }
    with SessionLocal() as db:
        db.add(StripeEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            status="COMPLETED",
            task=task,
            run_id=run_id,
            result_json=json.dumps(result),
        ))
        db.commit()
    return run_id


def test_same_task_other_tenant_does_not_leak_result(monkeypatch):
    tenant_a, key_a = _tenant()
    _tenant()
    session_a = "cs_a_" + uuid.uuid4().hex
    session_b = "cs_b_" + uuid.uuid4().hex
    _completed(session_b, task="same task")
    monkeypatch.setattr(main, "retrieve_checkout", lambda session_id: _session(tenant_a, session_a))
    response = TestClient(main.app).get(
        "/payment-success",
        params={"session_id": session_a},
        headers={"X-API-Key": key_a},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PAYMENT_CONFIRMED_EXECUTION_PENDING"
    assert "result" not in body and "run_id" not in body


def test_exact_checkout_session_returns_only_correct_result_to_owner(monkeypatch):
    tenant_a, key_a = _tenant()
    tenant_b, key_b = _tenant()
    session_a = "cs_a_" + uuid.uuid4().hex
    session_b = "cs_b_" + uuid.uuid4().hex
    _completed(session_b, run_id="wrong_tenant_run")
    expected_run = _completed(session_a, run_id="authorized_run")
    monkeypatch.setattr(main, "retrieve_checkout", lambda session_id: _session(tenant_a, session_a))
    client = TestClient(main.app)

    owned = client.get("/payment-success", params={"session_id": session_a},
                       headers={"X-API-Key": key_a})
    assert owned.status_code == 200, owned.text
    assert owned.json()["run_id"] == expected_run
    assert owned.json()["result"]["ola_final_result"] == {"owner": session_a}

    public = client.get("/payment-success", params={"session_id": session_a})
    assert public.status_code == 200
    assert public.json()["status"] == "PAYMENT_CONFIRMED"
    assert public.json()["execution"] == "AUTH_REQUIRED_FOR_STATUS"
    assert "task" not in public.json()
    assert "run_id" not in public.json()
    assert "result" not in public.json()

    outsider = client.get("/payment-success", params={"session_id": session_a},
                         headers={"X-API-Key": key_b})
    assert outsider.status_code in {403, 404}
    assert "authorized_run" not in outsider.text


def test_stripe_response_must_match_requested_session_id(monkeypatch):
    tenant_a, key_a = _tenant()
    monkeypatch.setattr(main, "retrieve_checkout", lambda session_id: _session(tenant_a, "cs_other"))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": "cs_requested"},
        headers={"X-API-Key": key_a},
    )
    assert response.status_code == 502


def test_duplicate_completed_events_for_one_session_fail_closed(monkeypatch):
    tenant_a, key_a = _tenant()
    session_id = "cs_dup_" + uuid.uuid4().hex
    _completed(session_id, run_id="first")
    _completed(session_id, run_id="second")
    monkeypatch.setattr(main, "retrieve_checkout", lambda requested: _session(tenant_a, session_id))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": session_id},
        headers={"X-API-Key": key_a},
    )
    assert response.status_code == 409


def test_incomplete_or_unverified_result_record_not_disclosed(monkeypatch):
    tenant_a, key_a = _tenant()
    session_id = "cs_invalid_" + uuid.uuid4().hex
    run_id = _completed(session_id)
    with SessionLocal() as db:
        event = db.query(StripeEvent).filter(StripeEvent.run_id == run_id).one()
        receipt = json.loads(event.result_json)
        receipt["payment"] = "UNCONFIRMED"
        event.result_json = json.dumps(receipt)
        db.commit()
    monkeypatch.setattr(main, "retrieve_checkout", lambda requested: _session(tenant_a, session_id))
    response = TestClient(main.app).get(
        "/payment-success", params={"session_id": session_id},
        headers={"X-API-Key": key_a},
    )
    assert response.status_code == 409
    assert "ola_final_result" not in response.text


def test_anonymous_payment_status_never_queries_execution_database(monkeypatch):
    tenant_a, _ = _tenant()
    session_id = "cs_public_" + uuid.uuid4().hex
    monkeypatch.setattr(main, "retrieve_checkout", lambda requested: _session(tenant_a, session_id))

    def forbidden_database_access():
        raise AssertionError("anonymous status must not query Stripe execution records")

    monkeypatch.setattr(main, "SessionLocal", forbidden_database_access)
    response = TestClient(main.app).get("/payment-success", params={"session_id": session_id})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "PAYMENT_CONFIRMED",
        "session_id": session_id,
        "execution": "AUTH_REQUIRED_FOR_STATUS",
    }
