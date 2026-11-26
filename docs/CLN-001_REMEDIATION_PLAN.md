# CLN-001 Remediation Plan

## Objective
Clean and simplify the existing OLA repository without creating a second system, adding product functionality, or weakening existing behavior.

Baseline: `main` at `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`.
Working branch: `cleanup/cln-001-safe-20261126`.

## Safety rules
- No deletion before HEAD, PR/history, reachability, unique code/files/tests, security/evidence, migrations, CI/workflow, operations/deployment and docs checks.
- `UNKNOWN`/insufficient evidence means retain and annotate.
- SALVAGE only narrowly scoped fixes that belong to the existing product.
- No product expansion through cleanup.
- New regression means NO-GO and rollback.

## Phase A — Branch reduction
### Completed risk qualification
`DELETE-VERIFIED` groups:
1. obsolete `cleanup/cln-001-safe` baseline branch;
2. agent-runtime minimal duplicate group `c87cb3c8...`;
3. final-production-gate duplicate pair `9990e9f...`;
4. staging/integration duplicate pair `6dff9c43...`;
5. runtime-attestation/integration duplicate group `8e56b33...`.

### Identical-tip discovery continues
Branches pages 1-3 have been inspected for exact HEAD duplicates. Next confirmed group:
- `fix/agent-runtime-source-binding-20261105`
- `verify/pr170-final-head-20261105`
Shared tip: `3f39ff8c1b705b501d86fcfa9572604596906e65`.
The source-binding branch has historical closed draft PR #170. Full risk analysis is next.

Queued after it:
- `fix/release-gate-workflow-path-binding-20261118` + `verify/release-gate-path-binding-final-20261118` at `62044a46b2971f061a0866d552a2c5460d92df5f`.
- `fix/supply-chain-exact-source-attestation-20261118` + `verify/supply-chain-exact-source-attestation-20261118` at `ded7a5f7f31b7dc078588f4d7cbcf692a4b72c5a`.

All queued groups remain `REVIEW` until the full delete gate passes.

## Phase B — SALVAGE-FIRST
Held until the current duplicate-discovery batch is reconciled:
- crypto-monitor group;
- PR #99 AI Studio/Aurora, with Human Gate fix isolated from Studio/UI material;
- PR #90 Events/Webhooks;
- PR #88 Verified Console;
- PR #86 Public CVE intelligence;
- PR #61 TRACEFORGE;
- PR #37 Decision Fabric/Jev.

## Phase C — Security/evidence reconciliation
Classify each security/evidence item as `ALREADY-IN-MAIN`, `MISSING-FIX`, `OBSOLETE`, or `SECURITY-HOLD`.

## Phase D — CI/workflow cleanup
Map workflow -> required check -> evidence -> ruleset/deployment dependency; consolidate/delete only after dependency proof.

## Phase E — Files/docs
Classify `USED`, `DEAD`, `GENERATED`, `DUPLICATE`, `UNKNOWN`; delete only proven dead/generated artifacts.

## Phase F — Regression/closure
Run existing relevant tests/build/security/evidence gates after mutating cleanup batches. Final merge requires no new failure, no lost required behavior and no weaker security/evidence posture.

## Current ordered queue
1. Analyze same-tip pair `3f39ff8c...`.
2. Analyze same-tip pair `62044a46...`.
3. Analyze same-tip pair `ded7a5f7...`.
4. Continue remaining identical-tip discovery.
5. Narrow SALVAGE-FIRST analysis beginning with PR #99 Human Gate change.
6. Security/evidence reconciliation.
7. Workflow/file cleanup.
8. Full regression and GO/NO-GO.
