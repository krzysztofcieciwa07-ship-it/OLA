"""Checkout creation is a payment-side effect: only synthetic Stripe calls here."""

import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import revenue
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import ApiKey, EvidenceRecord, StripeCheckoutRequest, Tenant


@pytest.fixture
def checkout_client(monkeypatch):
    tenant = str(uuid.uuid4())
    api_key = "checkout-key-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="checkout-creation-test"))
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=api_key_fingerprint(api_key)))
        db.commit()
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    return tenant, {"X-API-Key": api_key}, TestClient(app)


def _post(client, headers, key, *, task="Audit this workflow"):
    return client.post("/checkout", headers={**headers, "Idempotency-Key": key},
                       json={"task": task})


def _tenant_evidence(tenant):
    with SessionLocal() as db:
        return db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq)).all()


def test_duplicate_key_reuses_one_stripe_session_and_one_evidence(checkout_client, monkeypatch):
    tenant, headers, client = checkout_client
    calls = []

    def fake_stripe(task, success, cancel, tenant_id, *, idempotency_key):
        calls.append((task, tenant_id, idempotency_key))
        return {"id": "cs_test_" + uuid.uuid4().hex,
                "url": "https://checkout.stripe.com/c/pay/test", "amount_total": 9900}

    monkeypatch.setattr(revenue, "create_checkout", fake_stripe)
    key = "checkout-" + uuid.uuid4().hex
    first = _post(client, headers, key)
    second = _post(client, headers, key)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "READY_FOR_PAYMENT"
    assert len(calls) == 1 and calls[0][1] == tenant
    assert len(calls[0][2]) == 64 and calls[0][2] != key

    records = _tenant_evidence(tenant)
    assert [r.record_type for r in records] == ["revenue.checkout_created"]
    assert verify_chain([{
        "tenant_id": row.tenant_id, "seq": row.seq,
        "record_type": row.record_type, "payload_json": row.payload_json,
        "prev_hash": row.prev_hash, "record_hash": row.record_hash,
    } for row in records])[0]
    with SessionLocal() as db:
        intent = db.scalar(select(StripeCheckoutRequest).where(
            StripeCheckoutRequest.tenant_id == tenant))
        assert intent.status == "READY"
        assert intent.session_id == first.json()["session_id"]


def test_reuse_with_changed_request_fails_before_stripe(checkout_client, monkeypatch):
    _, headers, client = checkout_client
    calls = []
    monkeypatch.setattr(revenue, "create_checkout", lambda *a, **kw: (
        calls.append(True) or {"id": "cs_test_" + uuid.uuid4().hex,
                               "url": "https://checkout.stripe.com/test"}))
    key = "checkout-" + uuid.uuid4().hex
    assert _post(client, headers, key).status_code == 200
    changed = _post(client, headers, key, task="Different audit")
    assert changed.status_code == 409
    assert len(calls) == 1


def test_requires_client_retry_identity(checkout_client, monkeypatch):
    _, headers, client = checkout_client
    calls = []
    monkeypatch.setattr(revenue, "create_checkout", lambda *a, **kw: calls.append(True))
    for value in (None, "x", "contains spaces 12345"):
        req_headers = dict(headers)
        if value is not None:
            req_headers["Idempotency-Key"] = value
        res = client.post("/checkout", headers=req_headers, json={"task": "audit"})
        assert res.status_code == 400, res.text
    assert not calls


def test_network_ambiguity_cannot_trigger_checkout_retry(checkout_client, monkeypatch):
    tenant, headers, client = checkout_client
    calls = []

    def uncertain(*args, **kwargs):
        calls.append(True)
        raise TimeoutError("Stripe may have created the session")

    monkeypatch.setattr(revenue, "create_checkout", uncertain)
    key = "checkout-" + uuid.uuid4().hex
    assert _post(client, headers, key).status_code == 502
    assert _post(client, headers, key).status_code == 503
    assert len(calls) == 1
    with SessionLocal() as db:
        row = db.scalar(select(StripeCheckoutRequest).where(
            StripeCheckoutRequest.tenant_id == tenant))
        assert row.status == "UNCERTAIN"
    assert _tenant_evidence(tenant) == []


def test_crash_after_external_checkout_before_db_result_blocks_retry(checkout_client, monkeypatch):
    tenant, headers, client = checkout_client
    key = "checkout-" + uuid.uuid4().hex
    fingerprint = hashlib.sha256(
        f"ola.checkout.v1\0{tenant}\0{key}".encode()).hexdigest()
    payload_hash = hashlib.sha256(json.dumps([
        tenant, "Audit this workflow", "http://localhost:8000/payment-success",
        "http://localhost:8000/", "price_test_ola",
    ], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    with SessionLocal() as db:
        db.add(StripeCheckoutRequest(
            key_hash=fingerprint, tenant_id=tenant,
            request_hash=payload_hash, status="CREATING"))
        db.commit()
    calls = []
    monkeypatch.setattr(revenue, "create_checkout", lambda *a, **kw: calls.append(True))
    assert _post(client, headers, key).status_code == 503
    assert not calls


def test_same_client_key_is_tenant_scoped(checkout_client, monkeypatch):
    first_tenant, headers, client = checkout_client
    second_tenant = str(uuid.uuid4())
    second_key = "checkout-key-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=second_tenant, name="other-checkout-tenant"))
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=second_tenant,
                      key_hash=api_key_fingerprint(second_key)))
        db.commit()
    calls = []

    def fake_stripe(*args, **kwargs):
        calls.append(kwargs["idempotency_key"])
        return {"id": "cs_test_" + uuid.uuid4().hex,
                "url": "https://checkout.stripe.com/test"}

    monkeypatch.setattr(revenue, "create_checkout", fake_stripe)
    key = "checkout-" + uuid.uuid4().hex
    first = _post(client, headers, key)
    second = _post(client, {"X-API-Key": second_key}, key)
    assert first.status_code == second.status_code == 200
    assert first.json()["session_id"] != second.json()["session_id"]
    assert first_tenant != second_tenant and len(set(calls)) == 2


def test_evidence_failure_leaves_checkout_unrepeatable(checkout_client, monkeypatch):
    tenant, headers, client = checkout_client
    calls = []
    monkeypatch.setattr(revenue, "create_checkout", lambda *a, **kw: (
        calls.append(True) or {"id": "cs_test_" + uuid.uuid4().hex,
                               "url": "https://checkout.stripe.com/test"}))
    def fail_record(*args, **kwargs):
        raise RuntimeError("evidence unavailable")
    monkeypatch.setattr(revenue, "append_evidence_atomic", fail_record)
    key = "checkout-" + uuid.uuid4().hex
    assert _post(client, headers, key).status_code == 503
    assert _post(client, headers, key).status_code == 503
    assert len(calls) == 1
    with SessionLocal() as db:
        row = db.scalar(select(StripeCheckoutRequest).where(
            StripeCheckoutRequest.tenant_id == tenant))
        assert row.status == "EVIDENCE_PENDING"


def test_simultaneous_requests_do_not_both_call_stripe(checkout_client, monkeypatch):
    _, headers, _ = checkout_client
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_stripe(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return {"id": "cs_test_" + uuid.uuid4().hex,
                "url": "https://checkout.stripe.com/test"}

    monkeypatch.setattr(revenue, "create_checkout", fake_stripe)
    key = "checkout-" + uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_post, TestClient(app), headers, key)
        assert entered.wait(5)
        conflicting = _post(TestClient(app), headers, key)
        release.set()
        successful = first.result(timeout=10)
    assert successful.status_code == 200
    assert conflicting.status_code == 503
    assert len(calls) == 1
    assert _post(TestClient(app), headers, key).json() == successful.json()


def test_stripe_request_passes_scoped_idempotency_header(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake_local")
    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, *_):
            return b'{"id":"cs_test_test"}'

    def urlopen(req, timeout):
        captured["request"] = req
        return Response()

    monkeypatch.setattr(revenue.urllib.request, "urlopen", urlopen)
    revenue._stripe_request("checkout/sessions", {"mode": "payment"},
                            idempotency_key="scoped-checkout-key")
    assert captured["request"].get_header("Idempotency-key") == "scoped-checkout-key"
