# OLA — artifact staging, NOT delivery

Status: **DRAFT / CI VALIDATION / PRODUCTION NO-GO** (2026-10-26).
PR #136 is stacked on #135 → #134 → #133 → #132 → #119. The module
`app/delivery_artifacts.py` reuses the independent signed delivery reservation
from PR #133. There is no new payment engine or customer-facing endpoint.

## Exact boundaries

Signed Stripe event → `PENDING_HUMAN_AUTHORIZATION` (NO agent run) →
separately verified historic/approved run → dual Ed25519 IGOR/owner reservation
`DELIVERY_RESERVED` → operator artifact staging
`STAGED_AWAITING_PAYMENT_RECHECK`.

**Stop here.** No download, email, signed URL, entitlement, simulated
`DELIVERED`, retry or access to report content is performed by this module.
The reservation signer proof is *not* an independent binding between an
authenticated customer identity and `recipient_sha256`. No payment-refund
or dispute check occurs in this module.

A trusted operator provides an existing artifact filename, exact tenant,
Stripe Checkout Session ID, reservation UUID and recipient digest. The
operator must independently confirm recipient identity outside this module.

## Config and paths — use D: on HP ZBook

The artifact root **must already exist** and must not be a symlink; only
direct-child, non-symlink `.pdf`, `.zip`, `.json` filenames are accepted.
Limit: 25 MiB. No extraction, preview or arbitrary filesystem reads.

```powershell
# Existing operator-approved Windows environment; nothing is created here.
$env:OLA_DELIVERY_ARTIFACT_ROOT = 'D:\OLA\private-artifacts'
$env:OLA_EG_DB_PATH = 'D:\OLA\data\ola.db'
# Run from the checked-out exact reviewed commit; do NOT use a customer shell.
Set-Location 'D:\OLA'
python -c "from app.delivery_artifacts import stage_delivery; print('Operator module available; no order processed')"
```

Example invocation from a trusted Python operator console:

```python
from app.delivery_artifacts import stage_delivery

# All identifiers are copied from an independently reviewed order manifest,
# not from a buyer-controlled callback.
check = stage_delivery(
    tenant_id, checkout_session_id, reservation_id,
    "audit-report.pdf", recipient_sha256,
)  # dry_run=True by default; NO writes and NO sending

# Only after manual verification of the same identifiers:
staged = stage_delivery(
    tenant_id, checkout_session_id, reservation_id,
    "audit-report.pdf", recipient_sha256, dry_run=False,
)
# Returns STAGED_AWAITING_PAYMENT_RECHECK. NOT DELIVERED.
```

## Evidence / idempotency

- Read authenticated order tenant/session and matching `StripeEvent` state
  first. Reject missing or cross-tenant records.
- Independently revalidate the complete tenant Evidence v2 hash chain and
  `execution.delivery_reserved` proof from pinned IGOR + owner approvals.
- Hash the file from the approved root, compare exact digest and recipient
  hash against that reservation; reject symlinks, traversal and oversized
  files. The original signed manifest must already bind these identifiers.
- On explicit apply, in one SQLite `BEGIN IMMEDIATE` transaction:
  append trusted `execution.artifact_staged` Evidence and one
  `delivery_artifact_outbox` row keyed by immutable `reservation_id`.
- Identical replay validates artifact + full Evidence and returns
  `ALREADY_STAGED`; it never stages twice. A conflict or tampered chain
  blocks. Order itself stays `DELIVERY_RESERVED`.
- `delivery_sent=False` and `payment_rechecked=False` remain compulsory,
  not inferred from request metadata.

## What remains before customer delivery

1. **Payment recheck:** server-to-server authenticated Stripe session/payment
   and refund/dispute/chargeback reconciliation, with exact order identity.
   Unknown = BLOCKED. Snapshot alone is not enough against later disputes.
2. **Recipient authentication:** real customer portal session / SSO or a
   provider-verified recipient, separate from `X-API-Key` and unguessable
   one-shot grants tied to the signed recipient digest. Do not put API keys
   in browser localStorage or checkout redirects.
3. **Transport adapter:** object storage or authenticated download only after
   re-hashing the file *again* at dispatch; encrypted storage, expiry,
   authorized download, attempt ID, delivery receipt, and post-send
   reconciliation. Any uncertain external send must not auto-retry.
4. **Revoke on refunds:** separate entitlement state; never delete prior
   append-only Evidence.
5. **Real infrastructure:** production migrator for new table, SQLite
   crash/backup/restore tests, cross-process concurrency, full live
   Stripe TEST roundtrip and failure recovery.
6. **Governance:** production-bound source SHA, authorized commit signature,
   independent APPROVED review, `igor-independent` actually executed,
   real Human Gate and CI on exact final signed SHA.

Test command: `python -m pytest -q tests/test_delivery_artifacts.py`.
Temporary test signers are **not** real IGOR approval. No artifact is
delivered by passing these tests.
