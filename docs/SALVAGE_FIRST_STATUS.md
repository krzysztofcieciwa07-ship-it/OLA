# SALVAGE-FIRST Status Verification

This report verifies the currently annotated `SALVAGE-FIRST` branches. It does not merge them or add their features to `main`.

## Crypto monitor group
Branches:
- `fix/crypto-monitor-canonical-reconciliation`
- `fix/crypto-monitor-e2e-hardening`
- `feat/noncustodial-crypto-payment-monitor`

Status: `SALVAGE-FIRST / HOLD`.
Reason: shared tip is not proven reachable from current `main`; branch contains a complete `crypto_payment_monitor/` package and tests absent from current `main`; feature branch has historical closed draft PR #265. Product-scope decision and security review are required before selective salvage.

## PR #99 — AI Studio / Aurora integration
Branch: `integration/ai-studio-360-existing-runtime-20261012`.
Status: `SALVAGE-FIRST / SECURITY-REVIEW`.
Reason: contains multiple distinct changes: archive installer/verification, workflows and tests, extensive UI replacement, plus a Human Gate consistency hardening change in `app/main.py`. Do not merge as one unit. Security fix must be compared separately with current `main`; UI/Studio material requires explicit product-scope decision.

## PR #90 — Events/Webhooks integration
Branch: `integration/events-webhooks-20261012`.
Status: `SALVAGE-FIRST / HOLD`.
Reason: adds an isolated SQLite outbox package, tests, workflow and an integration document that explicitly marks production integration BLOCKED. This is not approved to enter the existing runtime without architecture, persistence, tenant, evidence and rollback reconciliation.

## PR #88 — Verified console
Branch: `feat/verified-console-20261011`.
Status: `SALVAGE-FIRST / COMPARE-WITH-MAIN`.
Reason: replaces the current console surface, adds API endpoints/assets, extensive browser/runtime tests and changes product-gate behavior. Requires exact file-by-file comparison with current `main`; no bulk merge.

## PR #86 — Public CVE intelligence
Branch: `feat/public-threat-intelligence-20261011`.
Status: `SALVAGE-FIRST / PRODUCT-SCOPE-HOLD`.
Reason: adds a new read-only threat-intelligence module and deterministic tests. This is a new product capability rather than cleanup. Preserve the branch, but do not integrate during repository hygiene.

## PR #61 — TRACEFORGE v0
Branch: `feat/traceforge-v0`.
Status: `SALVAGE-FIRST / PRODUCT-SCOPE-HOLD`.
Reason: adds a new TRACEFORGE package, runner, tests, docs and workflow. It is a separate capability and must not be introduced by cleanup.

## PR #37 — Decision Fabric / Jev
Branch: `feat/decision-fabric-jev`.
Status: `SALVAGE-FIRST / SECURITY-AND-PRODUCT-HOLD`.
Reason: adds a new external-provider decision layer, endpoint, evidence format, tests and workflow. It changes runtime behavior and depends on external credentials. Preserve for separate product/security review; do not integrate during cleanup.

## Summary
No current `SALVAGE-FIRST` branch is approved for deletion or bulk merge.

Permitted cleanup action: preserve branch/reference and annotation until a narrowly scoped comparison proves either:
1. the useful change is already present on current `main`, allowing `DELETE-VERIFIED`; or
2. a specific existing-system fix must be salvaged separately, tested and reviewed.

New modules and product surfaces remain outside CLN-001 cleanup scope.
