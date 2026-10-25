# Stripe Checkout fulfillment: one-session execution claim

Status: **LOCAL VERIFIED / PRODUCTION NO-GO**. Only signed synthetic Stripe
webhooks and mocked agent execution have been tested. This is not proof of a
real charge, independent customer delivery, or successful Stripe LIVE operation.

## Durable admission

`StripeCheckoutClaim` is a separate SQLite table keyed by the exact Stripe
`checkout_session_id`. Startup through `app.main` creates the table with
`Base.metadata.create_all`; the existing `stripe_events` and append-only
`evidence_records` schemas are unchanged.

For each signed, paid, completed Checkout Session:

1. SQLite `BEGIN IMMEDIATE` serializes writers before admission.
2. The first webhook atomically claims the Checkout Session and records its
   actual Stripe event ID, tenant, task, and `PROCESSING` state.
3. Repeated events for the same session and tenant can read back an already
   persisted outcome. While processing or after an unknown/failed outcome,
   additional attempts return HTTP 409 without executing an agent.
4. Conflicting tenant or task claims return HTTP 409. A different Stripe event
   ID cannot claim or execute the same Checkout Session again.
5. A missing/non-complete payment, signature error, or evidence failure never
   becomes `COMPLETED`. Failures are marked `FAILED` for reconciliation.

The original event ID remains in `stripe_events`; the new claim is a separate
order-level uniqueness constraint, not another evidence store. Successful local
agent results remain `PENDING_INDEPENDENT_VERIFICATION` until independent
IGOR/Human Gate approval and a separate release/delivery gate are implemented.

## Historical orders and recovery

- Existing results in `stripe_events` with a matching
  `result_json.checkout_session_id` but no new claim are **blocked (409)** for
  manual migration/reconciliation; they are never automatically replayed.
- Old `PROCESSING`/`FAILED` rows without a stored session ID cannot be safely
  tied to an order. All such rows must be reconciled with Stripe and immutable
  payment evidence before enabling this change in production.
- No automatic retries are performed after an uncertain agent/evidence outcome:
  a worker must prove whether execution already happened before any release.
- This implementation deliberately supports only SQLite's writer reservation.
  A PostgreSQL fulfillment backend needs a separate transactional admission
  review and currently receives HTTP 503.

## Remaining production gates

- Review and back up the actual deployed database; confirm the new table can be
  created and existing orders reconciled. No production migration was run.
- Add independent IGOR/Human Gate delivery authorization and a recoverable
  order state machine, without caller-supplied approval shortcuts.
- Integrate the execution safety gate on **every** runtime entry point,
  including the Stripe webhook (PR #120 currently protects `/agent-run` only).
- Decide whether to support delayed payment methods; currently only
  `checkout.session.completed` with `payment_status=paid` is handled.
- Verify Stripe test-mode webhook, real Checkout Session/tenant binding,
  exact-source CI, signed release provenance and independent review before GO.

Run locally: `python -m pytest -q tests/test_stripe_webhook_flow.py`, followed
by `python -m pytest -q`. No Stripe credentials are required for these tests.
