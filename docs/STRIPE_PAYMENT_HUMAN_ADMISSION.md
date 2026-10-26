# Payment-to-execution boundary — self-critical release note

Status: **STAGING / NOT MERGED / NO-GO**, 2026-10-26. Stacked on draft PR #119.

## Why this exists

A Stripe `checkout.session.completed` event can be signed and paid without any
independent human permission to execute the buyer-provided `task`. Previously
`app/stripe_webhook.py` called `run_agent_task(tenant_id, task)` directly
after recording payment. This bypassed the `/agent-run` route's separate
Safety Gate, and it happened before independent delivery authorization.
Payment authenticates neither an agent nor a production change.

## Current fail-closed contract

- Existing signature/time tolerance, offer, price, tenant and session claim
  admission logic stays in place. **Do not mistake EUR 99 (9,900 cents)
  configured for `ola-execution-audit` for the separate proposed EUR 490
  consulting offer.** Any new SKU needs its own reviewed contract.
- Signed, paid, valid webhook: store `stripe.payment_confirmed` and
  `stripe.fulfillment_held` (trusted append-only tenant evidence), then
  persist `PENDING_HUMAN_AUTHORIZATION` in both existing order claim and
  event rows. Return HTTP 200 and payment confirmation, *not an agent run*.
- Missing or failed evidence: never return `COMPLETED` or trigger execution;
  order goes to `FAILED` and manual reconciliation.
- Duplicate signed events (including different event IDs for one Checkout
  Session) reuse the existing durable hold. Conflicting tenant/session and
  uncertain claims remain blocked with no second execution.
- A buyer's metadata `human_approved=true`, `risk=LOW` or agent identifier is
  not an authenticated human approval. Never grant it authority.
- Historical `FAILED` / `PROCESSING` orders with real final agent evidence
  are still inspected with the existing proof-gated recovery procedure.
  Recovery can restore only `PENDING_INDEPENDENT_VERIFICATION`, never release
  or repeat execution. Tests seed old crash evidence explicitly; the new
  webhook does not reproduce an unsafe production path.
- There is deliberately **no automatic delivery API** in this change.

## Before any paid autonomous fulfillment

1. Unify every runtime entry point behind the same authenticated,
   tenant-scoped `ExecutionSafetyGate` with non-caller-supplied risk.
2. Create action-bound, authenticated, one-use Human Gate approval with
   independent approver and expiry. Payment cannot act as approval.
3. Define a post-approval execution admission record that is durable,
   idempotent and reconciles unknown external effects before any retry.
4. Verify `run_id`, exact source SHA, producer identity and full Evidence v2
   chain; obtain independent IGOR review distinct from executor.
5. Release only one tenant-scoped artifact to its intended recipient.
   Persist delivery receipt and reconcile download bounce/retry/expiry.
6. Reconcile refund/chargeback entitlement revocation, failed email and
   customer support; never silently erase append-only payment evidence.
7. Finish Stripe **TEST** real API/webhook roundtrip, database migration +
   restore, price catalog, async payment method policy, invoices and relevant
   local requirements. Accessible connected account was sandbox
   `livemode=false`; do not claim Stripe LIVE.
8. Sign final commits with authorized owner key, independently review them,
   verify required CI on the **exact signed SHA**, prove production recovery,
   protect `main`, and obtain explicit release Human Gate GO.

Manual EUR 490 B2B audit sales may proceed separately after commercial,
tax/invoicing, merchant-account and secure human-delivery requirements are met.
They do **not** enter this `ola-execution-audit` EUR 99 machine execution
flow.

## Verification / negative controls

CI must include signed but unauthorized payment, fake `human_approved`,
invalid signature, incomplete status, unknown tenant, duplicate event,
cross-tenant conflict, append failure, historical crash reconciliation,
full-chain validation and no `run_agent_task` call. Red baseline was
`5efcf093ea9d075cba4b44e9ba66b51565458e89` (expected assertion failures
from unauthorized execution). Passing tests mean the listed synthetic cases
were tested; **not** independent external payment or production operation.
