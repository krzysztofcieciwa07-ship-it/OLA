"""Read-only Stripe snapshot for an operator-staged artifact.

This is never an entitlement, dispatch authorization, a durable payment
approval or a substitute for a final provider recheck at delivery time.
"""
import json
import os
import re
import urllib.parse
import urllib.request

from .database import SessionLocal
from .delivery_artifacts import stage_delivery
from .models import StripeCheckoutClaim
from .revenue import retrieve_checkout
from .stripe_webhook import OLA_OFFER, OLA_PRODUCT


EXPECTED_AMOUNT_CENTS = 9900  # Existing fixed-price OLA Execution Audit offer
STRIPE_ID = re.compile(r"^(?:pi|ch)_[A-Za-z0-9_]+$")


def _stripe_get(path):
    """One authenticated Stripe GET; the caller supplies only fixed URL shapes."""
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise RuntimeError("Stripe API secret is missing")
    request = urllib.request.Request(
        "https://api.stripe.com/v1/" + path,
        headers={"Authorization": f"Bearer {secret}"}, method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _clean_snapshot(obj, expected_livemode):
    return (isinstance(obj, dict)
            and obj.get("livemode") is expected_livemode
            and obj.get("currency") == "eur")


def _empty_complete_list(value):
    return (isinstance(value, dict) and value.get("object") == "list"
            and value.get("has_more") is False and value.get("data") == [])


def inspect_staged_payment(tenant_id, session_id, reservation_id, filename,
                           recipient_sha256):
    """Return a non-binding Stripe snapshot; never persist or send anything.

    Local tenant, reservation, complete Evidence chain, exact artifact hash and
    staged outbox are checked before the first network call. Unknown or stale
    state is BLOCKED. Even a clear provider snapshot needs manual review and
    a *new* check at the future dispatch boundary.
    """
    blocked = {"status": "BLOCKED", "delivery_authorized": False,
               "payment_rechecked": False, "delivery_sent": False,
               "reservation_id": reservation_id}
    try:
        local = stage_delivery(
            tenant_id, session_id, reservation_id, filename,
            recipient_sha256, dry_run=True,
        )
        if local.get("status") != "ALREADY_STAGED":
            return blocked
        with SessionLocal() as db:
            claim = db.get(StripeCheckoutClaim, session_id)
            if claim is None or claim.tenant_id != tenant_id or claim.status != "DELIVERY_RESERVED":
                return blocked
            task = claim.task

        mode = os.getenv("OLA_STRIPE_EXPECT_LIVEMODE")
        if mode not in {"0", "1"}:
            return blocked
        expected_live = mode == "1"

        session = retrieve_checkout(session_id)
        if (not _clean_snapshot(session, expected_live)
                or session.get("object") != "checkout.session"
                or session.get("id") != session_id
                or session.get("mode") != "payment"
                or session.get("status") != "complete"
                or session.get("payment_status") != "paid"
                or session.get("amount_total") != EXPECTED_AMOUNT_CENTS
                or not isinstance(session.get("metadata"), dict)):
            return blocked
        metadata = session["metadata"]
        if (metadata.get("tenant_id") != tenant_id
                or metadata.get("task") != task
                or metadata.get("offer") != OLA_OFFER
                or metadata.get("product") != OLA_PRODUCT):
            return blocked

        payment_intent_id = session.get("payment_intent")
        if (not isinstance(payment_intent_id, str)
                or not STRIPE_ID.fullmatch(payment_intent_id)
                or not payment_intent_id.startswith("pi_")):
            return blocked
        intent = _stripe_get("payment_intents/" + urllib.parse.quote(payment_intent_id, safe=""))
        if (not _clean_snapshot(intent, expected_live)
                or intent.get("object") != "payment_intent"
                or intent.get("id") != payment_intent_id
                or intent.get("status") != "succeeded"
                or intent.get("amount_received") != EXPECTED_AMOUNT_CENTS):
            return blocked

        charge_id = intent.get("latest_charge")
        if (not isinstance(charge_id, str)
                or not STRIPE_ID.fullmatch(charge_id)
                or not charge_id.startswith("ch_")):
            return blocked
        charge = _stripe_get("charges/" + urllib.parse.quote(charge_id, safe=""))
        if (not _clean_snapshot(charge, expected_live)
                or charge.get("object") != "charge"
                or charge.get("id") != charge_id
                or charge.get("payment_intent") != payment_intent_id
                or charge.get("status") != "succeeded"
                or charge.get("paid") is not True
                or charge.get("captured") is not True
                or charge.get("amount") != EXPECTED_AMOUNT_CENTS
                or charge.get("amount_captured") != EXPECTED_AMOUNT_CENTS
                or charge.get("amount_refunded") != 0
                or charge.get("refunded") is not False
                or charge.get("disputed") is not False):
            return blocked

        query = "?payment_intent=" + urllib.parse.quote(payment_intent_id, safe="") + "&limit=1"
        # No refunds, including pending refunds, and no recorded disputes.
        # A partial/incomplete provider list is *never* treated as empty.
        if not _empty_complete_list(_stripe_get("refunds" + query)):
            return blocked
        if not _empty_complete_list(_stripe_get("disputes" + query)):
            return blocked
        return {**blocked, "status": "PROVIDER_SNAPSHOT_CLEAR_MANUAL_REVIEW"}
    except Exception:
        # Do not disclose Stripe errors, private IDs, API keys or tenant data.
        # Any uncertain network/local state blocks onward delivery.
        return blocked
