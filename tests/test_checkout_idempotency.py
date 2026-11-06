import uuid

from fastapi.testclient import TestClient

from app import main
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, Tenant, EvidenceRecord, CheckoutOrder
from sqlalchemy import select


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

    def create(task, success_url, cancel_url, tenant_id, idempotency_key, order_id):
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

    def create(task, success_url, cancel_url, tenant_id, idempotency_key, order_id):
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

    def create(task, success_url, cancel_url, tenant_id, idempotency_key, order_id):
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


def test_checkout_replay_repairs_missing_evidence_without_duplicate(monkeypatch):
    client, key = _client_and_key()
    original_append = main.append_record
    attempts = 0

    def fail_once(tenant_id, record_type, payload, *, deduplicate=False):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated evidence-store interruption")
        return original_append(
            tenant_id, record_type, payload, deduplicate=deduplicate
        )

    monkeypatch.setattr(main, "create_checkout", lambda *args, **kwargs: {
        "id": "cs_test_evidencerepair123",
        "url": "https://checkout.stripe.test/evidence-repair",
    })
    monkeypatch.setattr(main, "append_record", fail_once)
    client.raise_server_exceptions = False

    first = _checkout(client, key, "request-evidence-123")
    second = _checkout(client, key, "request-evidence-123")

    assert first.status_code == 500
    assert second.status_code == 200
    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.record_type == "revenue.checkout_created"
        )).all()
        orders = db.scalars(select(CheckoutOrder)).all()
    assert len([row for row in rows if "cs_test_evidencerepair123" in row.payload_json]) == 1
    assert len([order for order in orders if order.stripe_session_id == "cs_test_evidencerepair123"]) == 1


def test_checkout_ignores_caller_controlled_redirect_urls(monkeypatch):
    client, key = _client_and_key()
    captured = {}

    def create(task, success_url, cancel_url, tenant_id, idempotency_key, order_id):
        captured.update(success_url=success_url, cancel_url=cancel_url)
        return {"id": "cs_test_redirect123", "url": "https://checkout.stripe.test/redirect"}

    monkeypatch.setattr(main, "create_checkout", create)
    response = client.post(
        "/checkout",
        headers={"X-API-Key": key, "Idempotency-Key": "request-redirect-123"},
        json={
            "task": "verify redirect safety",
            "success_url": "https://attacker.example/collect",
            "cancel_url": "https://attacker.example/cancel",
        },
    )

    assert response.status_code == 200
    assert captured["success_url"] == "http://localhost:8000/payment-success"
    assert captured["cancel_url"] == "http://localhost:8000/"


def test_checkout_stale_reservation_fails_closed_after_provider_key_window(monkeypatch):
    import time

    client, key = _client_and_key()
    calls = []

    def create(*args, **kwargs):
        calls.append(kwargs.get("idempotency_key"))
        raise RuntimeError("simulated lost Stripe response")

    monkeypatch.setattr(main, "create_checkout", create)
    first = _checkout(client, key, "request-stale-12345")
    assert first.status_code == 502

    with SessionLocal() as db:
        order = db.scalar(select(CheckoutOrder).where(
            CheckoutOrder.idempotency_key_hash
            == __import__("hashlib").sha256(b"request-stale-12345").hexdigest()
        ))
        order.created_at = int(time.time()) - (24 * 60 * 60)
        db.commit()

    second = _checkout(client, key, "request-stale-12345")
    assert second.status_code == 409
    assert "manual Stripe reconciliation" in second.json()["detail"]
    assert len(calls) == 1
