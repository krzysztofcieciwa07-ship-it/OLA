import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from typing import Any


PRODUCT_NAME = "NINA Verified Audit"
DEFAULT_AMOUNT_EUR = 49


def _stripe_request(path: str, fields: dict[str, Any]) -> dict[str, Any]:
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    encoded = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        "https://api.stripe.com/v1/" + path,
        data=encoded,
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def create_checkout(task: str, success_url: str, cancel_url: str) -> dict[str, Any]:
    price_id = os.getenv("NINA_STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("NINA_STRIPE_PRICE_ID is not configured")
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
            "metadata[task]": task,
        },
    )


def retrieve_checkout(session_id: str) -> dict[str, Any]:
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    request = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions/" + urllib.parse.quote(session_id, safe=""),
        headers={"Authorization": f"Bearer {secret}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def payment_verified(session: dict[str, Any]) -> bool:
    return (
        session.get("payment_status") == "paid"
        and session.get("status") == "complete"
        and session.get("metadata", {}).get("product") == PRODUCT_NAME
    )


def verify_webhook_signature(payload: bytes, signature: str, secret: str, tolerance: int = 300) -> bool:
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
    signed = f"{timestamp}.{payload.decode()}".encode()
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)
