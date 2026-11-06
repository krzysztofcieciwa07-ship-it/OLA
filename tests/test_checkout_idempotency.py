import uuid

from fastapi.testclient import TestClient

from app import main
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, Tenant


def _client_and_key():
    tenant_id = str(uuid.uuid4())
    raw_key = f"checkout-key-{tenant_id}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="checkout-idempotency-test"))
        db.commit()
        db.add(ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(raw_key),
        ))
        db.commit()
    return TestClient(app), raw_key


def _checkout(client, key, idempotency_key, task="verify workflow"):
    return client.post(
        "/checkout",
        headers={
            "X-API-Key": key,
            "Idempotency-Key": idempotency_key,
        },
        json={"task": task},
    )


def test_checkout_reuses_existing_session_for_same_idempotency_key(monkeypatch):
    client, key = _client_and_key()
    calls = []

    def create(task, success_url, cancel_url, tenant_id, idempotency_key):
        calls.append((task, tenant_id, idempotency_key))
        return {"id": "cs_test_reused123", "url": "https://checkout.stripe.test/session"}

    monkeypatch.setattr(main, "create_checkout", create)
    first = _checkout(client, key, "request-12345678")
    second = _checkout(client, key, "request-12345678")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    assert first.json()["checkout_url"] == second.json()["checkout_url"]
    assert len(calls) == 1


def test_checkout_rejects_idempotency_key_reuse_for_different_task(monkeypatch):
    client, key = _client_and_key()
    calls = []

    def create(task, success_url, cancel_url, tenant_id, idempotency_key):
        calls.append(task)
        return {"id": "cs_test_taskbind123", "url": "https://checkout.stripe.test/session"}

    monkeypatch.setattr(main, "create_checkout", create)
    first = _checkout(client, key, "request-task-12345", "task A")
    second = _checkout(client, key, "request-task-12345", "task B")

    assert first.status_code == 200
    assert second.status_code == 409
    assert calls == ["task A"]


def test_checkout_retries_stripe_creation_with_same_provider_idempotency_key(monkeypatch):
    client, key = _client_and_key()
    provider_keys = []
    attempts = 0

    def create(task, success_url, cancel_url, tenant_id, idempotency_key):
        nonlocal attempts
        attempts += 1
        provider_keys.append(idempotency_key)
        if attempts == 1:
            raise RuntimeError("temporary Stripe outage")
        return {"id": "cs_test_retry123", "url": "https://checkout.stripe.test/retried"}

    monkeypatch.setattr(main, "create_checkout", create)
    first = _checkout(client, key, "request-retry-12345")
    second = _checkout(client, key, "request-retry-12345")

    assert first.status_code == 502
    assert second.status_code == 200
    assert len(provider_keys) == 2
    assert provider_keys[0] == provider_keys[1]


def test_checkout_requires_idempotency_key(monkeypatch):
    client, key = _client_and_key()
    called = []
    monkeypatch.setattr(main, "create_checkout", lambda *args, **kwargs: called.append(True))
    response = client.post("/checkout", headers={"X-API-Key": key}, json={"task": "verify"})

    assert response.status_code == 400
    assert called == []
