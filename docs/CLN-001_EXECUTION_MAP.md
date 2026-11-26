# CLN-001 Complete Execution Map

## Mission
Improve and simplify the existing OLA repository. Do not create a second system and do not introduce product features through cleanup.

## Canonical state
- baseline branch: `main`
- baseline SHA: `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`
- working branch: `cleanup/cln-001-safe-20261126`

## Decision states
`KEEP` | `WORKING` | `REVIEW` | `SALVAGE-FIRST` | `SECURITY-HOLD` | `HOLD-DEPENDENCY` | `DELETE-VERIFIED`

## Global delete gate
A branch is deleted only after checking:
1. HEAD SHA;
2. PR/reference dependency;
3. reachability from current `main`;
4. unique commits;
5. unique files/tests;
6. security/evidence/provenance;
7. database migrations;
8. CI/workflow dependencies;
9. operations/deployment material;
10. documentation.

If evidence is insufficient, retain and annotate.

## Track 1 — Snapshot and evidence
Status: ACTIVE / PASS TO DATE.
Artifacts:
- `CLEANUP_BASELINE_CLN-001.md`
- `BRANCH_RETENTION_ANNOTATIONS.md`
- branch risk reports
- `SALVAGE_FIRST_STATUS.md`
- `CLN-001_REMEDIATION_PLAN.md`

## Track 2 — Duplicate branch reduction
### DELETE-VERIFIED
- agent-runtime minimal duplicate group at `c87cb3c8...`.
- final-production-gate duplicate pair at `9990e9f...`.

### staging/integration same-tip pair `6dff9c43...`
Branches:
- `feat/ola-staging-bff-bootstrap-clean-20261108`
- `integration/jev-decision-fabric-20261106`
Evidence so far:
- same tip;
- tip modifies only `README.md`;
- commit is present in default-branch history;
- current `main` contains a later expanded README;
- no direct PR was found for either branch name.
Pending: final risk annotation, then `DELETE-VERIFIED` if no additional dependency appears.

### runtime-attestation group `8e56b33...`
Branches:
- `feat/runtime-image-attestation-20261107`
- `integration/ola-first-five-closure-20261106`
- `integration/replit-bff-recovery-20261107`
Status: `REVIEW`.
Next: ancestry, PRs, unique files/tests, release/evidence dependencies.

## Track 3 — SALVAGE-FIRST
- crypto-monitor group: HOLD; unique package absent from current main. No cleanup merge.
- PR #99 AI Studio/Aurora: split Human Gate/security comparison from UI/Studio product material.
- PR #90 Events/Webhooks: HOLD; isolated outbox must not become parallel persistence during cleanup.
- PR #88 Verified Console: exact comparison with current console only.
- PR #86 Public CVE intelligence: product-scope hold.
- PR #61 TRACEFORGE: product-scope hold.
- PR #37 Decision Fabric/Jev: security/product hold.

Rule: salvage only a narrowly scoped missing fix belonging to the existing product. Never bulk-merge a SALVAGE-FIRST branch.

## Track 4 — Security/evidence reconciliation
For every open security/evidence branch/PR:
- `ALREADY-IN-MAIN` -> superseded candidate;
- `MISSING-FIX` -> isolate only the fix and validate it;
- `OBSOLETE` -> retain annotation until safe closure/deletion;
- `UNCERTAIN` -> `SECURITY-HOLD`.

Priority areas: Human Gate, evidence chain/replay, tenant isolation, provenance, production gate, CodeQL, payment binding.

## Track 5 — CI/workflow cleanup
Build a mapping from workflow file to required check and evidence produced. Consolidate/delete only when no branch protection/ruleset/release path relies on the workflow and another canonical workflow covers the same required control.

## Track 6 — Files and documentation
Classify as `USED`, `DEAD`, `GENERATED`, `DUPLICATE`, `UNKNOWN`.
Delete only confirmed `DEAD` or tracked-generated artifacts after dependency review. Documentation must describe current executable behavior.

## Track 7 — Dependencies and security hygiene
Verify dependency files, secret handling, ignored runtime artifacts and redundant configuration. No dependency churn without a demonstrated cleanup/security reason.

## Track 8 — Regression
For each mutating cleanup batch run existing relevant tests/build/security/evidence gates and compare against baseline. New failure = NO-GO and rollback branch.

## Track 9 — Closure
Final requirements:
- no unresolved destructive action;
- all retained risky branches annotated;
- required functionality preserved;
- no weaker security/evidence behavior;
- docs consistent with current code;
- final GO/NO-GO recorded before merge.

## Track 10 — Ecosystem
After OLA closes successfully, apply the same inspect -> risk -> salvage -> clean -> validate process to the other accessible repositories. Do not copy OLA-specific product capabilities into them.
