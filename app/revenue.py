import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from typing import Any

PRODUCT_NAME = "OLA Execution Audit"
OFFER = "ola-execution-audit"


def stripe_secret_key() -> str:
    """Return a sandbox-only Stripe key; this checkout flow must never charge live cards."""
    secret = os.getenv("STRIPE_SECRET_KEY", "")
    if not secret.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError("OLA Stripe integration is sandbox-only; a Stripe test secret key is required")
    if os.getenv("STRIPE_EXPECT_LIVEMODE", "false").strip().lower() == "true":
        raise RuntimeError("OLA Stripe integration is sandbox-only; live mode is forbidden")
    return secret


def _stripe_request(path: str, fields: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
    secret = stripe_secret_key()
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency_key:
        if not isinstance(idempotency_key, str) or not idempotency_key.startswith("ola-checkout-"):
            raise ValueError("invalid OLA Stripe idempotency key")
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(
        "https://api.stripe.com/v1/" + path,
        data=urllib.parse.urlencode(fields).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def create_checkout(task, success_url, cancel_url, tenant_id, *, idempotency_key=None):
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


def retrieve_checkout(session_id):
    """Retrieve a sandbox Checkout Session through a fixed Stripe HTTPS host.

    Validate the path token before issuing the request. Keeping the hostname
    constant and using HTTPSConnection avoids turning an event-supplied value
    into a caller-controlled URL (SSRF).
    """
    import http.client
    import re

    if not isinstance(session_id, str) or not re.fullmatch(r"cs_test_[A-Za-z0-9]+", session_id):
        raise ValueError("invalid sandbox Checkout Session id")

    secret = stripe_secret_key()
    query = urllib.parse.urlencode({"expand[]": "line_items"})
    path = "/v1/checkout/sessions/" + session_id + "?" + query
    connection = http.client.HTTPSConnection("api.stripe.com", timeout=30)
    try:
        connection.request(
            "GET",
            path,
            headers={"Authorization": f"Bearer {secret}"},
        )
        response = connection.getresponse()
        body = response.read()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Stripe Checkout lookup failed with HTTP {response.status}")
        return json.loads(body)
    finally:
        connection.close()


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
