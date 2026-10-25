import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from typing import Any

from sqlalchemy import select

from .database import SessionLocal, append_evidence_atomic
from .models import StripeCheckoutRequest

PRODUCT_NAME = "OLA Execution Audit"
OFFER = "ola-execution-audit"


def _stripe_request(path: str, fields: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(
        "https://api.stripe.com/v1/" + path,
        data=urllib.parse.urlencode(fields).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def create_checkout(task, success_url, cancel_url, tenant_id, *, idempotency_key):
    price_id = os.getenv("OLA_STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("OLA_STRIPE_PRICE_ID is not configured")
    return _stripe_request(
        "checkout/sessions",
        {
            "mode": "payment",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": cancel_url,
            "client_reference_id": hashlib.sha256(task.encode()).hexdigest(),
            "metadata[product]": PRODUCT_NAME,
            "metadata[offer]": OFFER,
            "metadata[task]": task,
            "metadata[tenant_id]": tenant_id,
        },
        idempotency_key=idempotency_key,
    )


def create_checkout_once(task, success_url, cancel_url, tenant_id, client_key):
    """Fail-closed checkout creation with a tenant-scoped durable intent.

    A lost Stripe response is ambiguous: never create another Session for the
    same client key, even after Stripe's own idempotency retention expires.
    """
    price_id = os.getenv("OLA_STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("OLA_STRIPE_PRICE_ID is not configured")
    key_hash = hashlib.sha256(
        f"ola.checkout.v1\0{tenant_id}\0{client_key}".encode()
    ).hexdigest()
    request_hash = hashlib.sha256(json.dumps(
        [tenant_id, task, success_url, cancel_url, price_id],
        ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()

    with SessionLocal() as db:
        if db.bind.dialect.name != "sqlite":
            raise RuntimeError("checkout creation locking is unavailable")
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        existing = db.get(StripeCheckoutRequest, key_hash)
        if existing:
            if existing.tenant_id != tenant_id or existing.request_hash != request_hash:
                raise ValueError("idempotency key reused for a different checkout")
            if existing.status != "READY" or not existing.session_id or not existing.checkout_url:
                raise RuntimeError("checkout creation outcome requires reconciliation")
            return {"id": existing.session_id, "url": existing.checkout_url}
        db.add(StripeCheckoutRequest(
            key_hash=key_hash, tenant_id=tenant_id,
            request_hash=request_hash, status="CREATING",
        ))
        db.commit()

    try:
        session = create_checkout(task, success_url, cancel_url, tenant_id,
                                  idempotency_key=key_hash)
    except Exception:
        with SessionLocal() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = db.get(StripeCheckoutRequest, key_hash)
            if row and row.status == "CREATING":
                row.status = "UNCERTAIN"
                db.commit()
        raise

    if (not isinstance(session, dict)
            or not isinstance(session.get("id"), str) or not session["id"].startswith("cs_")
            or not isinstance(session.get("url"), str) or not session["url"].startswith("https://")):
        raise RuntimeError("Stripe returned an unverifiable checkout session")

    with SessionLocal() as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row = db.get(StripeCheckoutRequest, key_hash)
        if row is None or row.status != "CREATING":
            raise RuntimeError("checkout creation state changed unexpectedly")
        row.session_id = session["id"]
        row.checkout_url = session["url"]
        row.status = "EVIDENCE_PENDING"
        db.commit()

    # Only a persisted, source-bound checkout with a recorded evidence event is
    # returned to a client. Crashes in any intermediate state require review.
    append_evidence_atomic(tenant_id, "revenue.checkout_created", {
        "session_id": session["id"], "task": task,
        "amount": session.get("amount_total"), "checkout_request_hash": request_hash,
    })
    with SessionLocal() as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row = db.get(StripeCheckoutRequest, key_hash)
        if row is None or row.status != "EVIDENCE_PENDING":
            raise RuntimeError("checkout creation evidence state changed unexpectedly")
        row.status = "READY"
        db.commit()
    return {"id": session["id"], "url": session["url"]}


def retrieve_checkout(session_id):
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    req = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions/" + urllib.parse.quote(session_id, safe=""),
        headers={"Authorization": f"Bearer {secret}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def payment_verified(session):
    metadata = session.get("metadata", {})
    return (
        session.get("payment_status") == "paid"
        and session.get("status") == "complete"
        and metadata.get("product") == PRODUCT_NAME
        and metadata.get("offer") == OFFER
        and bool(metadata.get("tenant_id"))
        and bool(metadata.get("task"))
    )


def verify_webhook_signature(payload: bytes, signature: str, secret: str, tolerance: int = 300):
    if not signature or not secret:
        return False
    timestamp = None
    signatures = []
    for item in signature.split(","):
        key, _, value = item.partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    import time
    try:
        if abs(int(time.time()) - int(timestamp)) > tolerance:
            return False
    except ValueError:
        return False
    expected = hmac.new(
        secret.encode(),
        f"{timestamp}.{payload.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)
