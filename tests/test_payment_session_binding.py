"""Regression: a paid Checkout Session must be bound to its durable OLA order."""
import hashlib
import json
import uuid

from app import main
from app.database import SessionLocal
from app.models import CheckoutOrder, Tenant


TENANT_ID = "sandbox-unit-tenant"


def record_order(task, checkout_id, status, *, run_id=None):
    order_id = str(uuid.uuid4())
    result = None
    if status == "COMPLETED":
        result = {
            "status": "COMPLETED",
            "checkout_session_id": checkout_id,
            "event_id": "test-event",
            "run_id": run_id,
            "ola_run_id": run_id,
        }
    elif status == "PAID_PENDING_REVIEW":
        result = {
            "status": "PAID_PENDING_REVIEW",
            "checkout_session_id": checkout_id,
            "payment": "CONFIRMED",
            "ola_run_id": None,
        }
    with SessionLocal() as db:
        if db.get(Tenant, TENANT_ID) is None:
            db.add(Tenant(id=TENANT_ID, name="payment-session-test"))
            db.commit()
        db.add(CheckoutOrder(
            id=order_id,
            tenant_id=TENANT_ID,
            idempotency_key_hash=uuid.uuid4().hex,
            request_hash=hashlib.sha256(task.encode()).hexdigest(),
            task=task,
            status=status,
            stripe_session_id=checkout_id,
            checkout_url="https://checkout.stripe.test/session",
            payment_result_json=json.dumps(result) if result else None,
        ))
        db.commit()
    return order_id


def paid_session(checkout_id, task, order_id):
    return {
        "id": checkout_id, "livemode": False,
        "payment_status": "paid", "status": "complete",
        "metadata": {
            "product": "OLA Execution Audit", "offer": "ola-execution-audit",
            "tenant_id": TENANT_ID, "task": task, "order_id": order_id,
        },
    }


def test_payment_success_returns_status_without_durable_order_details(monkeypatch):
    task = "same audit request " + str(uuid.uuid4())
    record_order(task, "cs_test_first", "COMPLETED", run_id="run_first")
    second_order_id = record_order(task, "cs_test_second", "COMPLETED", run_id="run_second")
    monkeypatch.setattr(
        main, "retrieve_checkout",
        lambda sid: paid_session(sid, task, second_order_id),
    )
    established_contexts = []
    monkeypatch.setattr(main, "set_current_tenant_id", established_contexts.append)

    result = main.payment_success("cs_test_second")
    assert established_contexts == [TENANT_ID]

    assert result["status"] == "COMPLETED"
    assert result["customer_delivery"] == "NOT_DELIVERED"
    assert "run_id" not in result
    assert "result" not in result
    assert "task" not in result
    assert "session_id" not in result


def test_payment_success_does_not_disclose_another_session_result(monkeypatch):
    task = "same audit request " + str(uuid.uuid4())
    record_order(task, "cs_test_another", "COMPLETED", run_id="run_other")
    new_order_id = record_order(task, "cs_test_brand_new", "CHECKOUT_CREATED")
    monkeypatch.setattr(
        main, "retrieve_checkout",
        lambda sid: paid_session(sid, task, new_order_id),
    )

    result = main.payment_success("cs_test_brand_new")

    assert result["status"] == "PAYMENT_VERIFICATION_PENDING"
    assert "result" not in result
    assert "run_id" not in result


def test_payment_success_reports_human_review_hold_without_execution(monkeypatch):
    task = "review pending audit " + str(uuid.uuid4())
    order_id = record_order(task, "cs_test_review_hold", "PAID_PENDING_REVIEW")
    monkeypatch.setattr(
        main, "retrieve_checkout",
        lambda sid: paid_session(sid, task, order_id),
    )

    result = main.payment_success("cs_test_review_hold")

    assert result["status"] == "PAID_PENDING_REVIEW"
    assert result["payment"] == "CONFIRMED"
    assert result["execution"] == "NOT_STARTED"
    assert result["next_gate"] == "HUMAN_REVIEW"
    assert "run_id" not in result


def test_payment_success_rejects_session_with_another_orders_binding(monkeypatch):
    task = "binding check " + str(uuid.uuid4())
    order_id = record_order(task, "cs_test_bound", "CHECKOUT_CREATED")
    monkeypatch.setattr(
        main, "retrieve_checkout",
        lambda sid: paid_session(sid, task, order_id),
    )

    with SessionLocal() as db:
        order = db.get(CheckoutOrder, order_id)
        order.stripe_session_id = "cs_test_different"
        db.commit()

    from fastapi import HTTPException
    try:
        main.payment_success("cs_test_bound")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("unbound Checkout Session must be rejected")


def test_payment_success_never_discloses_private_report_or_task(monkeypatch):
    task = "CONFIDENTIAL CUSTOMER TASK " + str(uuid.uuid4())
    session_id = "cs_test_private_report"
    order_id = record_order(task, session_id, "EXECUTED_REVIEW_REQUIRED")
    private_report = {"customer_secret": "DO_NOT_DISCLOSE_" + uuid.uuid4().hex}
    with SessionLocal() as db:
        order = db.get(CheckoutOrder, order_id)
        order.payment_result_json = json.dumps({
            "status": "EXECUTED_REVIEW_REQUIRED",
            "checkout_session_id": session_id,
            "task": task,
            "run_id": "private-run-id",
            "report": private_report,
            "execution": "COMPLETED",
            "customer_delivery": "NOT_DELIVERED",
        })
        db.commit()
    monkeypatch.setattr(
        main, "retrieve_checkout",
        lambda sid: paid_session(sid, task, order_id),
    )

    result = main.payment_success(session_id)
    serialized = json.dumps(result, sort_keys=True)

    assert result["status"] == "EXECUTED_REVIEW_REQUIRED"
    assert result["customer_delivery"] == "NOT_DELIVERED"
    assert result["next_gate"] == "CUSTOMER_REPORT_REVIEW"
    for forbidden in (
        "task", "result", "report", "run_id", "session_id", "order_id",
        "payment_evidence_id", "evidence_tip_hash", "approval_record_hash",
    ):
        assert forbidden not in result
    assert "DO_NOT_DISCLOSE_" not in serialized
    assert task not in serialized
