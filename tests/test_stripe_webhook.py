import hashlib
import hmac
import json
import time
import uuid

import pytest

from app import stripe_webhook
from app.stripe_webhook import _validate_checkout, verify_stripe_signature
from app.database import SessionLocal
from app.models import Tenant, CheckoutOrder


SECRET = "whsec_test_ola"
TIMESTAMP = 1_800_000_000


def _signature(payload: bytes, timestamp: int = TIMESTAMP) -> str:
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _paid_session():
    return {
        "id": "cs_test_" + str(uuid.uuid4()),
        "livemode": False,
        "metadata": {
            "offer": "ola-execution-audit",
            "product": "OLA Execution Audit",
            "task": "Audit this company workflow for evidence gaps.",
            "tenant_id": "tenant-test",
            "order_id": str(uuid.uuid4()),
        },
        "payment_status": "paid",
        "status": "complete",
        "amount_total": 9900,
        "currency": "eur",
        "line_items": {
            "data": [{"price": {"id": "price_test_ola", "unit_amount": 9900, "currency": "eur"}, "quantity": 1}]
        },
    }


def _seed_checkout_order(session):
    metadata = session["metadata"]
    with SessionLocal() as db:
        if db.get(Tenant, metadata["tenant_id"]) is None:
            db.add(Tenant(id=metadata["tenant_id"], name="stripe-webhook-test"))
            db.commit()
        db.add(CheckoutOrder(
            id=metadata["order_id"],
            tenant_id=metadata["tenant_id"],
            idempotency_key_hash=uuid.uuid4().hex,
            request_hash=hashlib.sha256(metadata["task"].encode()).hexdigest(),
            status="CHECKOUT_CREATED",
            stripe_session_id=session["id"],
            checkout_url="https://checkout.stripe.test/session",
        ))
        db.commit()


def test_stripe_signature_accepts_valid_signature():
    payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
    assert verify_stripe_signature(payload, _signature(payload), SECRET, now=TIMESTAMP)


def test_stripe_signature_rejects_tampered_payload():
    payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
    signature = _signature(payload)
    tampered = b'{"id":"evt_test","type":"checkout.session.completed","x":"tampered"}'
    assert not verify_stripe_signature(tampered, signature, SECRET, now=TIMESTAMP)


def test_stripe_signature_rejects_old_timestamp():
    payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
    signature = _signature(payload)
    assert not verify_stripe_signature(payload, signature, SECRET, now=TIMESTAMP + 301)


def test_paid_ola_checkout_extracts_audit_task(monkeypatch):
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    assert _validate_checkout(_paid_session()) == "Audit this company workflow for evidence gaps."


@pytest.mark.parametrize(
    "override",
    [
        {"payment_status": "unpaid"},
        {"amount_total": 9800},
        {"currency": "usd"},
        {"metadata": {"offer": "other-offer", "product": "OLA Execution Audit", "task": "x"}},
    ],
)
def test_invalid_checkout_is_rejected(monkeypatch, override):
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    session.update(override)
    with pytest.raises(Exception):
        _validate_checkout(session)


def test_paid_checkout_uses_metadata_task_without_custom_fields(monkeypatch):
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    assert "custom_fields" not in session
    assert _validate_checkout(session) == "Audit this company workflow for evidence gaps."


def test_paid_webhook_queues_review_and_never_executes_automatically(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")

    def forbidden_execution(*args, **kwargs):
        raise AssertionError("payment confirmation must not execute an OLA task")

    monkeypatch.setattr(stripe_webhook, "run_agent_task", forbidden_execution, raising=False)
    session = _paid_session()
    _seed_checkout_order(session)
    monkeypatch.setattr(stripe_webhook, "retrieve_checkout", lambda session_id: session)
    event = {
        "id": "evt_review_" + str(uuid.uuid4()),
        "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": session},
    }
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    result = stripe_webhook.process_checkout_event(
        payload, _signature(payload, timestamp)
    )

    assert result["status"] == "PAID_PENDING_REVIEW"
    assert result["payment"] == "CONFIRMED"
    assert result["ola_status"] == "NOT_STARTED"
    assert result["ola_run_id"] is None
    assert result["execution_authorized"] is False



def test_webhook_uses_authoritative_stripe_session_not_event_object(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    authoritative = _paid_session()
    _seed_checkout_order(authoritative)
    event_object = {
        "id": authoritative["id"],
        "payment_status": "paid",
        "amount_total": 9900,
        "currency": "eur",
        "metadata": {"offer": "attacker-controlled"},
    }
    calls = []
    monkeypatch.setattr(
        stripe_webhook,
        "retrieve_checkout",
        lambda session_id: calls.append(session_id) or authoritative,
    )
    event = {
        "id": "evt_authoritative_" + str(uuid.uuid4()),
        "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": event_object},
    }
    payload = json.dumps(event, separators=(",", ":")).encode()
    result = stripe_webhook.process_checkout_event(
        payload, _signature(payload, int(time.time()))
    )
    assert calls == [authoritative["id"]]
    assert result["status"] == "PAID_PENDING_REVIEW"


def test_webhook_rejects_live_event_even_if_environment_requests_live(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("STRIPE_EXPECT_LIVEMODE", "true")
    event = {
        "id": "evt_live_" + str(uuid.uuid4()),
        "type": "checkout.session.completed",
        "livemode": True,
        "data": {"object": {"id": "cs_live_forbidden"}},
    }
    payload = json.dumps(event, separators=(",", ":")).encode()
    with pytest.raises(Exception):
        stripe_webhook.process_checkout_event(
            payload, _signature(payload, int(time.time()))
        )


def test_checkout_requires_exact_configured_price_and_quantity(monkeypatch):
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    session["line_items"]["data"][0]["price"]["id"] = "price_other"
    with pytest.raises(Exception):
        _validate_checkout(session)


@pytest.mark.parametrize("data", [None, "invalid", [], {}, {"object": None}, {"object": []}])
def test_webhook_rejects_malformed_event_data_without_crashing(monkeypatch, data):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    event = {
        "id": "evt_malformed_" + str(uuid.uuid4()),
        "type": "checkout.session.completed",
        "livemode": False,
        "data": data,
    }
    payload = json.dumps(event, separators=(",", ":")).encode()
    with pytest.raises(Exception) as exc:
        stripe_webhook.process_checkout_event(
            payload, _signature(payload, int(time.time()))
        )
    assert getattr(exc.value, "status_code", None) == 400


def test_paid_checkout_accepts_configured_price_amount_without_hardcoded_ola_price(monkeypatch):
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    session["amount_total"] = 14700
    session["line_items"]["data"][0]["price"].update({
        "unit_amount": 14700,
        "currency": "eur",
    })
    assert _validate_checkout(session) == "Audit this company workflow for evidence gaps."


@pytest.mark.parametrize(
    "price_patch,quantity",
    [
        ({"unit_amount": None}, 1),
        ({"unit_amount": 0}, 1),
        ({"unit_amount": 9900, "currency": "usd"}, 1),
        ({"unit_amount": 9900, "currency": "eur"}, True),
    ],
)
def test_checkout_rejects_invalid_price_amount_currency_or_boolean_quantity(
    monkeypatch, price_patch, quantity
):
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    session["line_items"]["data"][0]["price"].update(price_patch)
    session["line_items"]["data"][0]["quantity"] = quantity
    with pytest.raises(Exception):
        _validate_checkout(session)


def test_webhook_recovers_after_partial_evidence_write_without_duplicate_records(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    _seed_checkout_order(session)
    monkeypatch.setattr(stripe_webhook, "retrieve_checkout", lambda session_id: session)

    event = {
        "id": "evt_recover_" + str(uuid.uuid4()),
        "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": session},
    }
    payload = json.dumps(event, separators=(",", ":")).encode()
    signature = _signature(payload, int(time.time()))
    original_append = stripe_webhook._append_evidence
    calls = 0

    def fail_second_append(tenant_id, record_type, record_payload, *, deduplicate=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated evidence interruption")
        return original_append(
            tenant_id, record_type, record_payload, deduplicate=deduplicate
        )

    monkeypatch.setattr(stripe_webhook, "_append_evidence", fail_second_append)
    with pytest.raises(RuntimeError):
        stripe_webhook.process_checkout_event(payload, signature)

    monkeypatch.setattr(stripe_webhook, "_append_evidence", original_append)
    result = stripe_webhook.process_checkout_event(payload, signature)

    assert result["status"] == "PAID_PENDING_REVIEW"
    assert result["order_id"] == session["metadata"]["order_id"]
    assert result["execution_authorized"] is False
    with SessionLocal() as db:
        order = db.get(CheckoutOrder, session["metadata"]["order_id"])
        confirmed = db.query(__import__("app.models", fromlist=["EvidenceRecord"]).EvidenceRecord).filter_by(
            tenant_id="tenant-test", record_type="stripe.payment_confirmed"
        ).all()
        pending = db.query(__import__("app.models", fromlist=["EvidenceRecord"]).EvidenceRecord).filter_by(
            tenant_id="tenant-test", record_type="stripe.payment_pending_review"
        ).all()
    assert order.status == "PAID_PENDING_REVIEW"
    assert len(confirmed) == 1
    assert len(pending) == 1


def test_distinct_duplicate_webhook_events_for_paid_session_do_not_duplicate_payment(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OLA_STRIPE_PRICE_ID", "price_test_ola")
    session = _paid_session()
    _seed_checkout_order(session)
    monkeypatch.setattr(stripe_webhook, "retrieve_checkout", lambda session_id: session)

    def send(event_id):
        event = {
            "id": event_id,
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": session},
        }
        payload = json.dumps(event, separators=(",", ":")).encode()
        return stripe_webhook.process_checkout_event(
            payload, _signature(payload, int(time.time()))
        )

    first = send("evt_first_" + str(uuid.uuid4()))
    second = send("evt_second_" + str(uuid.uuid4()))

    assert first["status"] == "PAID_PENDING_REVIEW"
    assert second == first
    with SessionLocal() as db:
        confirmed = db.query(__import__("app.models", fromlist=["EvidenceRecord"]).EvidenceRecord).filter_by(
            tenant_id="tenant-test", record_type="stripe.payment_confirmed"
        ).all()
    assert len(confirmed) == 1
