# CLN-001 Remediation Plan

## Objective
Clean and simplify the existing OLA repository without creating a second system, adding product functionality, or weakening existing behavior.

Canonical baseline for this cleanup: `main` at `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`.
Working branch: `cleanup/cln-001-safe-20261126`.

## Non-negotiable rules
1. Existing executable code and tests are the source of truth.
2. No branch deletion before risk/dependency review.
3. `UNKNOWN` means retain and annotate.
4. Unique useful material is salvaged only when it belongs to the existing product; cleanup must not introduce a new module or product surface.
5. Security/evidence/provenance/migrations remain on hold until reconciled with current `main`.
6. Work in small batches; new regression means NO-GO and rollback.
7. No force-push to `main`.
8. A successful rollback does not convert a failed cleanup into GO.

## Phase A — Branch reduction
### A1. DELETE-VERIFIED sets
- Agent-runtime duplicate group (`c87cb3c8...`): delete branch references when deletion operation is available.
- Final-production-gate duplicate pair (`9990e9f...`): delete branch references when deletion operation is available.

### A2. Duplicate groups still under review
- staging/integration pair (`6dff9c43...`).
- runtime-attestation/integration group (`8e56b33...`).

For each: HEAD, PR/history dependency, reachability from `main`, unique files/tests, security/evidence, migrations, CI/workflows, operations/deployment and docs.

## Phase B — SALVAGE-FIRST reconciliation
Current hold set:
- crypto-monitor duplicate group: unique package absent from current `main`; do not merge as cleanup.
- PR #99 AI Studio/Aurora: split security fix analysis from UI/Studio product material.
- PR #90 Events/Webhooks: isolated outbox is not approved to become a parallel runtime/persistence path during cleanup.
- PR #88 Verified Console: compare file-by-file with current `main`; salvage only existing-system fixes that remain missing.
- PR #86 Public CVE intelligence: product-scope hold.
- PR #61 TRACEFORGE: product-scope hold.
- PR #37 Decision Fabric/Jev: security/product hold.

## Phase C — Security and evidence reconciliation
Review open security/evidence PR heads against current `main`. For each, classify:
- `ALREADY-IN-MAIN` -> PR/branch may become superseded after evidence check.
- `MISSING-FIX` -> isolate only the required fix on cleanup branch, run existing regression/security tests, then review.
- `OBSOLETE` -> annotate reason; no salvage.
- `UNCERTAIN` -> `SECURITY-HOLD`.

## Phase D — CI/workflow cleanup
Inventory current workflows and map each to an existing required gate. Do not remove a workflow because of age/name alone. Remove/consolidate only after proving its required check is duplicated or obsolete and branch/ruleset references no longer depend on it.

## Phase E — Files and documentation
Classify files as `USED`, `DEAD`, `GENERATED`, `DUPLICATE`, or `UNKNOWN`. Delete only `DEAD`/`GENERATED` items after dependency checks. Documentation must describe current executable behavior, not proposals.

## Phase F — Regression and closure
Run existing repository tests/build/security/evidence gates against cleanup branch and compare to baseline. Required outcome: no new failures, no lost required feature, no weaker security/evidence behavior. Only then prepare final GO/NO-GO for merge.

## Current execution queue
1. Analyze staging/integration same-tip pair `6dff9c43...`.
2. Analyze runtime-attestation/integration same-tip group `8e56b33...`.
3. Compare PR #99 Human Gate change against current `main` independently of AI Studio/Aurora material.
4. Compare PR #88 console behavior against current `main`.
5. Reconcile remaining security/evidence PRs.
6. Audit workflow duplication and required-check dependencies.
7. Dead-file/document cleanup.
8. Full regression and final GO/NO-GO.

## Evidence documents
- `docs/CLEANUP_BASELINE_CLN-001.md`
- `docs/BRANCH_RETENTION_ANNOTATIONS.md`
- `docs/BRANCH_RISK_AGENT_RUNTIME_DUPLICATES.md`
- `docs/BRANCH_RISK_CRYPTO_MONITOR_DUPLICATES.md`
- `docs/BRANCH_RISK_FINAL_PRODUCTION_GATE_DUPLICATES.md`
- `docs/SALVAGE_FIRST_STATUS.md`
