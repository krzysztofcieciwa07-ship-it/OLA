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
- Identical tips prove identical Git content, not absence of external references.
- Reachability and semantic supersession are separate gates.
- Plan, Execution Map and Retention Registry must be updated consistently before a final destructive disposition.

## Phase A — Branch reduction
### Completed risk qualification
`DELETE-VERIFIED` groups:
1. obsolete `cleanup/cln-001-safe` baseline branch;
2. agent-runtime minimal duplicate group `c87cb3c8...`;
3. final-production-gate duplicate pair `9990e9f...`;
4. staging/integration duplicate pair `6dff9c43...`;
5. runtime-attestation/integration duplicate group `8e56b33...`;
6. source-binding/PR170 duplicate pair `3f39ff8c...`.

### `62044a46...` release-gate path-binding pair
Branches:
- `fix/release-gate-workflow-path-binding-20261118`
- `verify/release-gate-path-binding-final-20261118`

Status: `SALVAGE-FIRST / SECURITY-HOLD`.

Evidence:
- tip changes `final-production-gate.yml` to correct the import of `scripts.release_gate`;
- branch contains `scripts/release_gate.py` with exact PR/head/base binding, canonical workflow-path filtering and exact-main-run filtering;
- branch contains `tests/test_release_gate_pr_scope.py` covering wrong PR/base/head/event, spoofed workflow name/path, missing paths and invalid/duplicate paths;
- current `main` does not contain `scripts/release_gate.py` or `test_release_gate_pr_scope.py` and its final production gate selects required runs primarily by workflow name;
- branch `test_release_source_binding.py` also contains additional release-gate regression assertions not present in the current main version.

Decision: no branch deletion. Before reconsideration, selectively port only the missing release-evidence identity/path protections onto current code, preserve fail-closed semantics, and validate with release-source/release-gate regression tests.

### Next duplicate group
- `fix/supply-chain-exact-source-attestation-20261118`
- `verify/supply-chain-exact-source-attestation-20261118`
Shared tip: `ded7a5f7f31b7dc078588f4d7cbcf692a4b72c5a`.
Status: `REVIEW` until the full high-risk gate completes.

## Mandatory high-risk analysis checklist
Before any new disposition:
1. exact branch/ref and current HEAD;
2. PR/history and branch-name dependencies;
3. ancestry/reachability evidence distinct from semantic supersession;
4. unique commits/files/tests/docs/scripts;
5. security/evidence/provenance and Human Gate effects;
6. migrations/data compatibility;
7. CI, ruleset, release, deployment and attestation dependencies;
8. worst-case consequence of a wrong deletion;
9. explicit assumptions, missing evidence, weakest evidence and counterargument;
10. post-write verification of control documents.

Tool/read failure is not positive evidence. An affected destructive decision remains blocked while unrelated read-only inventory may continue.

## Phase B — SALVAGE-FIRST
Current hold set:
- release-gate path-binding pair `62044a46...`;
- crypto-monitor group;
- PR #99 AI Studio/Aurora, Human Gate fix isolated from Studio/UI material;
- PR #90 Events/Webhooks;
- PR #88 Verified Console;
- PR #86 Public CVE intelligence;
- PR #61 TRACEFORGE;
- PR #37 Decision Fabric/Jev.

## Phase C — Security/evidence reconciliation
Classify each item as `ALREADY-IN-MAIN`, `MISSING-FIX`, `OBSOLETE`, or `SECURITY-HOLD`.

## Phase D — CI/workflow cleanup
Map workflow -> required check -> evidence -> ruleset/deployment dependency; consolidate/delete only after dependency proof.

## Phase E — Files/docs
Classify `USED`, `DEAD`, `GENERATED`, `DUPLICATE`, `UNKNOWN`; delete only proven dead/generated artifacts.

## Phase F — Regression/closure
Run relevant tests/build/security/evidence gates after mutating cleanup batches. Final merge requires no new failure, no lost required behavior and no weaker security/evidence posture.

## Current ordered queue
1. Analyze same-tip pair `ded7a5f7...`.
2. Continue remaining identical-tip discovery.
3. Prepare minimal salvage design for `62044a46...` without bulk cherry-pick.
4. Narrow SALVAGE-FIRST analysis beginning with PR #99 Human Gate change.
5. Security/evidence reconciliation.
6. Workflow/file cleanup.
7. Full regression and GO/NO-GO.
