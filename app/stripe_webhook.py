import hashlib
import hmac
import json
import os
import re
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal, append_evidence_atomic
from .hashchain import canonical_json
from .models import StripeEvent, CheckoutOrder, CheckoutOrderControl
from .revenue import retrieve_checkout
from .tenant_context import set_current_tenant_id


STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300
OLA_OFFER = "ola-execution-audit"
OLA_PRODUCT = "OLA Execution Audit"


def verify_stripe_signature(payload: bytes, signature_header: str, secret: str, now: int | None = None) -> bool:
    if not signature_header or not secret:
        return False
    timestamp = None
    signatures = []
    for item in signature_header.split(","):
        key, _, value = item.partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > STRIPE_SIGNATURE_TOLERANCE_SECONDS:
        return False
    signed = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def _append_evidence(tenant_id: str, record_type: str, payload: dict, *, deduplicate=False) -> str:
    return append_evidence_atomic(tenant_id, record_type, payload, deduplicate=deduplicate)["id"]


def _metadata_task(session: dict) -> str | None:
    metadata = session.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    task = metadata.get("task")
    if isinstance(task, str) and task.strip():
        return task.strip()
    custom_fields = session.get("custom_fields")
    if not isinstance(custom_fields, list):
        return None
    for field in custom_fields:
        if not isinstance(field, dict) or field.get("key") != "audit_task":
            continue
        text_field = field.get("text")
        value = text_field.get("value") if isinstance(text_field, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validate_checkout(session: dict) -> str:
    metadata = session.get("metadata")
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="Stripe session metadata is invalid")
    session_id = session.get("id")
    if not isinstance(session_id, str) or not session_id.startswith("cs_test_"):
        raise HTTPException(status_code=400, detail="invalid sandbox Checkout Session identity")
    if session.get("livemode") is not False:
        raise HTTPException(status_code=400, detail="live Stripe sessions are forbidden")
    if metadata.get("offer") != OLA_OFFER:
        raise HTTPException(status_code=400, detail="unsupported Stripe offer")
    if metadata.get("product") != OLA_PRODUCT:
        raise HTTPException(status_code=400, detail="unsupported Stripe product")
    if session.get("payment_status") != "paid" or session.get("status") != "complete":
        raise HTTPException(status_code=400, detail="payment is not confirmed")
    if session.get("currency") != "eur":
        raise HTTPException(status_code=400, detail="unexpected payment currency")

    expected_price = os.getenv("OLA_STRIPE_PRICE_ID", "").strip()
    if not expected_price:
        raise HTTPException(status_code=503, detail="Stripe sandbox Price ID is not configured")
    line_items = session.get("line_items")
    items = line_items.get("data") if isinstance(line_items, dict) else None
    if not isinstance(items, list) or len(items) != 1:
        raise HTTPException(status_code=400, detail="exactly one Stripe line item is required")
    item = items[0]
    price = item.get("price") if isinstance(item, dict) else None
    quantity = item.get("quantity") if isinstance(item, dict) else None
    unit_amount = price.get("unit_amount") if isinstance(price, dict) else None
    price_currency = price.get("currency") if isinstance(price, dict) else None
    amount_total = session.get("amount_total")
    if (
        not isinstance(price, dict)
        or price.get("id") != expected_price
        or isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity != 1
        or isinstance(unit_amount, bool)
        or not isinstance(unit_amount, int)
        or unit_amount <= 0
        or price_currency != "eur"
        or isinstance(amount_total, bool)
        or not isinstance(amount_total, int)
        or amount_total != unit_amount * quantity
    ):
        raise HTTPException(status_code=400, detail="unexpected Stripe price, amount, currency or quantity")

    request_hash = metadata.get("request_hash")
    if isinstance(request_hash, str) and re.fullmatch(r"[0-9a-f]{64}", request_hash):
        return request_hash

    # Compatibility for sessions created before request_hash-only metadata.
    # Legacy text is never re-persisted to StripeEvent or payment evidence.
    legacy_task = _metadata_task(session)
    if not legacy_task:
        raise HTTPException(status_code=400, detail="checkout request hash is required")
    return hashlib.sha256(legacy_task.encode("utf-8")).hexdigest()


def process_checkout_event(payload: bytes, signature_header: str) -> dict:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not verify_stripe_signature(payload, signature_header, secret):
        raise HTTPException(status_code=400, detail="invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid Stripe JSON") from exc

    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Stripe event must be an object")
    event_id = event.get("id")
    event_type = event.get("type")
    if not isinstance(event_id, str) or not event_id or not isinstance(event_type, str) or not event_type:
        raise HTTPException(status_code=400, detail="Stripe event id and type are required")

    if event.get("livemode") is not False:
        raise HTTPException(status_code=400, detail="live Stripe events are forbidden")

    if event_type != "checkout.session.completed":
        return {"status": "IGNORED", "event_id": event_id, "event_type": event_type}

    event_data = event.get("data")
    event_session = event_data.get("object") if isinstance(event_data, dict) else None
    session_id = event_session.get("id") if isinstance(event_session, dict) else None
    if not isinstance(session_id, str) or not session_id.startswith("cs_test_"):
        raise HTTPException(status_code=400, detail="invalid sandbox Checkout Session reference")

    try:
        session = retrieve_checkout(session_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="authoritative Stripe session lookup failed") from exc
    if not isinstance(session, dict) or session.get("id") != session_id:
        raise HTTPException(status_code=502, detail="Stripe returned a different Checkout Session")
    request_hash = _validate_checkout(session)
    metadata = session.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")
    order_id = metadata.get("order_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise HTTPException(status_code=400, detail="Stripe session has no tenant provenance")
    if not isinstance(order_id, str) or not order_id.strip():
        raise HTTPException(status_code=400, detail="Stripe session has no OLA order binding")

    set_current_tenant_id(tenant_id)

    # Claim the order with a conditional update. Only one Stripe event may own
    # the transition from CHECKOUT_CREATED to PAYMENT_PROCESSING.
    with SessionLocal() as db:
        order = db.get(CheckoutOrder, order_id)
        if (
            order is None
            or order.tenant_id != tenant_id
            or order.stripe_session_id != session_id
        ):
            raise HTTPException(status_code=409, detail="Stripe session is not bound to this OLA order")
        if order.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Stripe session request hash does not match the OLA order",
            )
        task = order.task
        if not isinstance(task, str) or not task.strip():
            legacy_task = _metadata_task(session)
            if legacy_task and hashlib.sha256(legacy_task.encode("utf-8")).hexdigest() == order.request_hash:
                task = legacy_task
                order.task = task
                db.commit()
        if not isinstance(task, str) or not task.strip() or hashlib.sha256(task.encode("utf-8")).hexdigest() != order.request_hash:
            raise HTTPException(
                status_code=409,
                detail="private OLA order task is missing or does not match its request hash; manual reconciliation required",
            )
        if order.status == "PAID_PENDING_REVIEW" and order.payment_result_json:
            try:
                return json.loads(order.payment_result_json)
            except (ValueError, TypeError):
                raise HTTPException(status_code=503, detail="durable payment result is invalid") from None
        if order.status == "CHECKOUT_CREATED":
            claimed = db.execute(
                update(CheckoutOrder)
                .where(
                    CheckoutOrder.id == order_id,
                    CheckoutOrder.status == "CHECKOUT_CREATED",
                )
                .values(status="PAYMENT_PROCESSING", payment_event_id=event_id)
            )
            if claimed.rowcount != 1:
                db.rollback()
                order = db.get(CheckoutOrder, order_id)
                if not (
                    order is not None
                    and order.status == "PAYMENT_PROCESSING"
                    and order.payment_event_id == event_id
                ):
                    raise HTTPException(status_code=409, detail="another Stripe event owns this OLA order")
        elif not (
            order.status == "PAYMENT_PROCESSING"
            and order.payment_event_id == event_id
        ):
            raise HTTPException(status_code=409, detail="OLA order is not eligible for payment recovery")
        db.commit()

        existing = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        if existing is not None:
            if existing.status in {"REVIEW_REQUIRED", "COMPLETED"} and existing.result_json:
                return json.loads(existing.result_json)
            if existing.status != "PROCESSING":
                raise HTTPException(status_code=409, detail="Stripe event is not recoverable")
        else:
            db.add(StripeEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_id=event_id,
                status="PROCESSING",
                task=None,
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
                if existing is None or existing.status != "PROCESSING":
                    raise HTTPException(status_code=409, detail="Stripe event is already being processed") from None

    payment_evidence_id = _append_evidence(
        tenant_id,
        "stripe.payment_confirmed",
        {
            "ola_order_id": order_id,
            "stripe_event_id": event_id,
            "checkout_session_id": session_id,
            "offer": OLA_OFFER,
            "product": OLA_PRODUCT,
            "amount_total": session.get("amount_total"),
            "currency": session.get("currency"),
            "request_hash": request_hash,
            "execution_authorized": False,
            "review_required": True,
        },
        deduplicate=True,
    )

    result = {
        "status": "PAID_PENDING_REVIEW",
        "event_id": event_id,
        "order_id": order_id,
        "checkout_session_id": session_id,
        "payment": "CONFIRMED",
        "ola_status": "NOT_STARTED",
        "ola_run_id": None,
        "payment_evidence_id": payment_evidence_id,
        "execution_authorized": False,
        "next_gate": "HUMAN_REVIEW",
    }
    _append_evidence(
        tenant_id,
        "stripe.payment_pending_review",
        {
            "ola_order_id": order_id,
            "stripe_event_id": event_id,
            "checkout_session_id": session_id,
            "payment_evidence_id": payment_evidence_id,
            "execution_authorized": False,
            "next_gate": "HUMAN_REVIEW",
        },
        deduplicate=True,
    )

    with SessionLocal() as db:
        completed = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        order = db.get(CheckoutOrder, order_id)
        if completed is None or order is None or order.payment_event_id != event_id:
            raise HTTPException(status_code=503, detail="payment recovery state unavailable")
        completed.status = "REVIEW_REQUIRED"
        completed.run_id = None
        completed.result_json = canonical_json(result)
        order.status = "PAID_PENDING_REVIEW"
        order.payment_result_json = canonical_json(result)
        control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == order_id,
            CheckoutOrderControl.tenant_id == tenant_id,
        ))
        if control is not None:
            control.status = "PAID_PENDING_REVIEW"
            control.payment_evidence_id = payment_evidence_id
        db.commit()

    return result
