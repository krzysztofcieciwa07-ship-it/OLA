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
  absence of records is **not** proof that execution did not happen.
- This implementation deliberately supports only SQLite's writer reservation.
  A PostgreSQL fulfillment backend needs a separate transactional admission
  review and currently receives HTTP 503.

### Recovery CLI (operator-only)

From the repository root, with `OLA_EG_DB_PATH` pointing to the intended OLA
SQLite database (verify that path before running):

```bash
# Read-only inspection; does not call Stripe or run an agent.
python -m scripts.reconcile_stripe_orders cs_test_example

# Only if complete local payment + agent + finish evidence verifies.
python -m scripts.reconcile_stripe_orders cs_test_example --apply
```

The default is read-only. `--apply` cannot retry an audit or mark an order
`COMPLETED`. For `PROCESSING`/`FAILED`, it requires all of the following:

1. Valid **entire tenant hash-chain**, with trusted server-bound v2 records.
2. Exactly one matching payment event and one final execution event, with the
   original Checkout Session, Stripe event ID, tenant, task and payment
   evidence ID coherently bound.
3. A unique agent `run_id` with every expected agent record between payment
   and completion, plus `verify_agent_run` returning `VERIFIED`.
4. Consistent mutable claim/event state, with no pre-existing result to replace.

On success, the transaction atomically updates only the two mutable order
states to `PENDING_INDEPENDENT_VERIFICATION`, restores their result data, and
appends `execution.stripe_order_reconciled` to the append-only evidence chain.
There is **no customer delivery** and no independent Human Gate approval.

If final execution evidence is absent, ambiguous, tampered with, or submitted
through the tenant API rather than the trusted runtime writer, recovery stays
`UNCERTAIN`/`BLOCKED`; retry is forbidden. The mechanism cannot conclude
`NOT_EXECUTED` from missing evidence. Any decision to rerun such work requires
external incident reconciliation and a separately designed, authorized recovery
policy. CLI access must be restricted to an operator with access to the OLA DB;
it is not exposed as a public HTTP endpoint.

## Remaining production gates

- Review and back up the actual deployed database; confirm the new table can be
  created and existing orders reconciled. No production migration was run.
- Add independently authorized IGOR/Human Gate customer delivery, and a
  separately audited recovery path for cases where no execution proof exists.
- Integrate the execution safety gate on **every** runtime entry point,
  including the Stripe webhook (PR #120 currently protects `/agent-run` only).
- Decide whether to support delayed payment methods; currently only
  `checkout.session.completed` with `payment_status=paid` is handled.
- Verify Stripe test-mode webhook, real Checkout Session/tenant binding,
  exact-source CI, signed release provenance and independent review before GO.

Run locally: `python -m pytest -q tests/test_stripe_recovery.py`, then
`python -m pytest -q`. No Stripe credentials are required for these tests.
