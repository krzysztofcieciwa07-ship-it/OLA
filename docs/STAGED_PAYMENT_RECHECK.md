# Staged artifact payment recheck — read-only, no release authorization

Status: **draft candidate; production NO-GO**. This adds a fail-closed,
provider-backed **snapshot**, not a delivery/entitlement mechanism.

Before any Stripe call, `inspect_staged_payment` validates that the requested
tenant/session has an existing signed delivery reservation **and** a staged
artifact, verifies the *entire* tenant Evidence chain, and hashes the current
artifact against the signed proof. Missing or altered local data blocks.

The Stripe API reads then verify:

1. Checkout Session: exact tenant, task, offer, product, session ID, mode,
   EUR 99.00, completed and paid; exact TEST vs LIVE mode.
2. PaymentIntent: exact ID, succeeded, EUR 99.00 received, latest charge.
3. Charge: captured and paid, expected amount and currency, no partial/full
   refund, no recorded dispute.
4. Refund list and dispute list: both fully empty, rather than inferring
   innocence from a single charge flag. Unknown/partial API results BLOCK.

Stripe's official API documentation for
[Checkout Sessions](https://docs.stripe.com/api/checkout/sessions/retrieve),
[PaymentIntents](https://docs.stripe.com/api/payment_intents/retrieve),
[refund listing](https://docs.stripe.com/api/refunds/list), and
[dispute listing](https://docs.stripe.com/api/disputes/list) defines these
server-side lookups.

## Trusted operator example (Windows HP ZBook, D:)

Configure an existing private DB, artifact directory, and a correctly scoped
Stripe secret in the *operator process*. Never put a secret in the command line
or in browser local storage.

```powershell
$env:OLA_EG_DB_PATH = 'D:\OLA\data\ola.db'
$env:OLA_DELIVERY_ARTIFACT_ROOT = 'D:\OLA\private-artifacts'
$env:OLA_STRIPE_EXPECT_LIVEMODE = '0' # Stripe TEST; set 1 only for reviewed LIVE use
# STRIPE_SECRET_KEY must be provisioned securely in this operator session.
Set-Location 'D:\OLA'
python -m scripts.inspect_staged_payment `
  --tenant-id '<trusted-tenant-uuid>' `
  --session-id '<trusted-checkout-session-id>' `
  --reservation-id '<trusted-reservation-uuid>' `
  --filename 'audit-report.pdf' `
  --recipient-sha256 '<64-char-recipient-digest>'
```

Only a current clean snapshot returns
`PROVIDER_SNAPSHOT_CLEAR_MANUAL_REVIEW`, with **all three values**
`delivery_authorized=false`, `payment_rechecked=false`,
`delivery_sent=false`. A non-clear result exits with code 2.
The routine never modifies a database row, grants an entitlement or sends
customer data. A snapshot can become stale immediately: the future delivery
worker MUST independently re-query provider state **at dispatch time**,
re-hash the artifact, confirm authenticated recipient identity and record
transport receipt. Refund/chargeback revocation remains unimplemented.

## Gates still missing

- Real authenticated customer portal, identity-to-recipient binding, storage,
  one-time delivery and trusted transport receipt.
- Robust production DB migration and backup/restore verification.
- Stripe TEST end-to-end demonstration and provider permission/timeout review.
- Signed, production-bound source, executed independent IGOR, independent
  GitHub approval, explicit Human Gate and fresh CI on final SHA.

Test: `python -m pytest -q tests/test_staged_payment_recheck.py`.
