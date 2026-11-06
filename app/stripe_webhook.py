import hashlib
import hmac
import json
import os
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal, append_evidence_atomic
from .hashchain import canonical_json
from .models import StripeEvent


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


def _append_evidence(tenant_id: str, record_type: str, payload: dict) -> str:
    return append_evidence_atomic(tenant_id, record_type, payload)["id"]


def _metadata_task(session: dict) -> str | None:
    metadata = session.get("metadata") or {}
    task = metadata.get("task")
    if isinstance(task, str) and task.strip():
        return task.strip()
    for field in session.get("custom_fields", []) or []:
        if field.get("key") == "audit_task":
            value = field.get("text", {}).get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _validate_checkout(session: dict) -> str:
    metadata = session.get("metadata") or {}
    if not isinstance(session.get("id"), str) or not session["id"].startswith("cs_"):
        raise HTTPException(status_code=400, detail="invalid Checkout Session identity")
    if metadata.get("offer") != OLA_OFFER:
        raise HTTPException(status_code=400, detail="unsupported Stripe offer")
    if metadata.get("product") not in {None, OLA_PRODUCT}:
        raise HTTPException(status_code=400, detail="unsupported Stripe product")
    if session.get("payment_status") != "paid" or session.get("status") not in {None, "complete"}:
        raise HTTPException(status_code=400, detail="payment is not confirmed")
    if session.get("currency") != "eur" or session.get("amount_total") != 9900:
        raise HTTPException(status_code=400, detail="unexpected payment amount or currency")
    line_items = session.get("line_items") or {}
    if isinstance(line_items, dict):
        price_ids = {
            item.get("price", {}).get("id")
            for item in line_items.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("price"), dict)
        }
        expected_price = os.getenv("OLA_STRIPE_PRICE_ID")
        if price_ids and expected_price and price_ids != {expected_price}:
            raise HTTPException(status_code=400, detail="unexpected Stripe price")
    task = _metadata_task(session)
    if not task:
        raise HTTPException(status_code=400, detail="audit task is required")
    return task


def process_checkout_event(payload: bytes, signature_header: str) -> dict:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not verify_stripe_signature(payload, signature_header, secret):
        raise HTTPException(status_code=400, detail="invalid Stripe signature")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid Stripe JSON") from exc

    event_id = event.get("id")
    event_type = event.get("type")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Stripe event id and type are required")

    expected_livemode = os.getenv("STRIPE_EXPECT_LIVEMODE", "false").strip().lower() == "true"
    if not isinstance(event.get("livemode"), bool) or event["livemode"] is not expected_livemode:
        raise HTTPException(status_code=400, detail="unexpected Stripe account mode")

    if event_type != "checkout.session.completed":
        return {"status": "IGNORED", "event_id": event_id, "event_type": event_type}

    session = event.get("data", {}).get("object", {})
    task = _validate_checkout(session)
    tenant_id = (session.get("metadata") or {}).get("tenant_id") or os.getenv("OLA_STRIPE_TENANT_ID", "")
    if not tenant_id:
        raise HTTPException(status_code=500, detail="Stripe session has no tenant provenance")

    with SessionLocal() as db:
        existing = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        if existing is not None:
            if existing.status in {"REVIEW_REQUIRED", "COMPLETED"} and existing.result_json:
                return json.loads(existing.result_json)
            raise HTTPException(status_code=409, detail="Stripe event is already being processed")

        record = StripeEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            status="PROCESSING",
            task=task,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Stripe event is already being processed") from None

    payment_evidence_id = _append_evidence(
        tenant_id,
        "stripe.payment_confirmed",
        {
            "stripe_event_id": event_id,
            "checkout_session_id": session["id"],
            "offer": OLA_OFFER,
            "product": OLA_PRODUCT,
            "amount_total": session.get("amount_total"),
            "currency": session.get("currency"),
            "task": task,
            "execution_authorized": False,
            "review_required": True,
        },
    )

    result = {
        "status": "PAID_PENDING_REVIEW",
        "event_id": event_id,
        "checkout_session_id": session["id"],
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
            "stripe_event_id": event_id,
            "checkout_session_id": session["id"],
            "payment_evidence_id": payment_evidence_id,
            "execution_authorized": False,
            "next_gate": "HUMAN_REVIEW",
        },
    )

    with SessionLocal() as db:
        completed = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        completed.status = "REVIEW_REQUIRED"
        completed.run_id = None
        completed.result_json = canonical_json(result)
        db.commit()

    return result
