# CLN-001 Complete Execution Map

## Mission
Improve and simplify the existing OLA repository. Do not create a second system and do not introduce product features through cleanup.

## Canonical state
- baseline: `main` at `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`
- working branch: `cleanup/cln-001-safe-20261126`

## Global delete gate
Before deletion: HEAD -> PR/history -> main reachability -> unique commits/files/tests -> security/evidence/provenance -> migrations -> CI/workflow -> operations/deployment -> docs. Insufficient evidence = retain and annotate.

## Track 1 — Evidence and registry
Status: ACTIVE.
Current evidence set includes baseline, retention registry, remediation plan, SALVAGE-FIRST status and branch-risk reports.

## Track 2 — Duplicate branch reduction
### Completed as DELETE-VERIFIED
- obsolete `cleanup/cln-001-safe`.
- agent-runtime minimal group `c87cb3c8...`.
- final-production-gate pair `9990e9f...`.
- staging/integration pair `6dff9c43...`.
- runtime-attestation/integration group `8e56b33...`.

### Current group
`3f39ff8c1b705b501d86fcfa9572604596906e65`
- `fix/agent-runtime-source-binding-20261105`
- `verify/pr170-final-head-20261105`
Known dependency: closed draft PR #170 is associated with the source-binding branch.
Status: `REVIEW`; full risk analysis next.

### Queue
1. `62044a46b2971f061a0866d552a2c5460d92df5f`
   - `fix/release-gate-workflow-path-binding-20261118`
   - `verify/release-gate-path-binding-final-20261118`
2. `ded7a5f7f31b7dc078588f4d7cbcf692a4b72c5a`
   - `fix/supply-chain-exact-source-attestation-20261118`
   - `verify/supply-chain-exact-source-attestation-20261118`

All queued groups remain `REVIEW`.

## Track 3 — SALVAGE-FIRST
Unchanged hold set: crypto-monitor; PR #99 AI Studio/Aurora; PR #90 Events/Webhooks; PR #88 Verified Console; PR #86 Public CVE intelligence; PR #61 TRACEFORGE; PR #37 Decision Fabric/Jev.

## Track 4 — Security/evidence reconciliation
After duplicate discovery batch: classify `ALREADY-IN-MAIN`, `MISSING-FIX`, `OBSOLETE`, `SECURITY-HOLD`.

## Track 5 — CI/workflow cleanup
After branch reconciliation, map required checks and dependencies before any workflow deletion/consolidation.

## Track 6 — Files/docs
Classify `USED`, `DEAD`, `GENERATED`, `DUPLICATE`, `UNKNOWN`.

## Track 7 — Dependencies/security hygiene
Minimal changes only; no dependency churn without cleanup/security evidence.

## Track 8 — Regression
Run existing relevant tests/build/security/evidence gates after mutating batches. Regression = NO-GO/rollback.

## Track 9 — Closure
Final GO requires preserved functionality, no weaker controls, no unresolved destructive actions and documentation matching executable behavior.

## Track 10 — Ecosystem
Only after OLA closes: apply the same bounded process to the other accessible repositories.
