# Branch Risk Report: runtime-attestation/integration duplicate group

## Branches
- `feat/runtime-image-attestation-20261107`
- `integration/ola-first-five-closure-20261106`
- `integration/replit-bff-recovery-20261107`

Shared tip: `8e56b33df9a3e2806f3709fca90b07e4e595d28f`.

## Tip change
The shared tip modifies only `.github/workflows/paid-order-postgres.yml`, adding exact candidate source SHA binding to checkout and an explicit mismatch failure check.

## Reachability
The exact commit is returned by default-branch commit search. Assessment: `REACHABLE FROM DEFAULT-BRANCH HISTORY`.

## Current-main comparison
Current `main` contains the same exact-source binding behavior in `.github/workflows/paid-order-postgres.yml`: `EXPECTED_SOURCE_SHA`, checkout at the PR head/current SHA, `persist-credentials: false`, and the explicit checkout SHA assertion. The current workflow also contains the PostgreSQL contract service and test execution around it.

Assessment: the shared-tip behavior is represented on current `main`.

## Remaining dependency gate
Before `DELETE-VERIFIED`, check PR/history references for all three branch names. Until that search is complete, status remains `REVIEW`.

## Risk to date
- Code loss: LOW; tip changes CI only.
- Test loss: LOW; current main retains the PostgreSQL contract tests in the workflow.
- Workflow/security loss: LOW based on tip/current-main comparison.
- Migration loss: NONE IDENTIFIED by tip change.
- PR/reference risk: PENDING.

## Current disposition
`REVIEW` pending direct PR/history dependency checks. Do not delete yet.
