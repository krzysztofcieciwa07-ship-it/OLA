# SALVAGE evidence: `62044a46b2971f061a0866d552a2c5460d92df5f`

## Scope

Source branches:
- `fix/release-gate-workflow-path-binding-20261118`
- `verify/release-gate-path-binding-final-20261118`

Current disposition: `SALVAGE-FIRST / SECURITY-HOLD`.

This document applies the CLN-001 salvage checklist. It does not authorize merge, cherry-pick, branch deletion, or modification of `main`.

## Checklist result

### S0 — source freeze
- [x] exact shared source SHA recorded;
- [x] both source branch names recorded;
- [x] no source branch mutation performed;
- [x] no bulk cherry-pick or merge performed.

### S1/S2 — salvage candidates

| ID | Source | Candidate | Classification | Current-main equivalent | Result |
|---|---|---|---|---|---|
| A | `scripts/release_gate.py` | PR/head/base identity filtering | SECURITY-FIX / FAIL-CLOSED | none found | SALVAGE |
| B | `scripts/release_gate.py` | canonical workflow-name-to-path filtering | SECURITY-FIX / CI-SAFETY | none found | SALVAGE |
| C | `tests/test_release_gate_pr_scope.py` | negative tests for wrong PR/base/head/event | REGRESSION-TEST | none found | SALVAGE |
| D | `tests/test_release_gate_pr_scope.py` | spoofed workflow name/path rejection | REGRESSION-TEST | none found | SALVAGE |
| E | `final-production-gate.yml` | call identity/path filters before name selection | CI/RELEASE-SAFETY | current gate selects by display name | SALVAGE-DESIGN |
| F | branch `test_release_source_binding.py` additions | candidate-SHA producer and main-branch lookup assertions | REGRESSION-TEST | partial coverage only | REVIEW-SEPARATELY |

## Threat and failure model

The missing control is workflow-run identity. A display name alone is not a sufficient identity when selecting release evidence. The salvage target binds release evidence to:
- exact PR number;
- exact head SHA and head branch;
- exact base SHA and base branch;
- canonical workflow path for the expected workflow name;
- or, for main evidence, exact SHA, `main`, and an explicit event allowlist.

## S3 — negative comparison

The proposed salvage must not:
- replace the current final-production gate wholesale;
- remove current exact-source checkout, image revision checks, attestations, nested gate checks, or Human Gate semantics;
- restore stale required-gate lists or API query structure;
- introduce migrations, runtime code paths, product features, or alternate persistence;
- weaken `BLOCKED`, `PREMERGE_CI_PASSED`, or `ATTESTED_PENDING_HUMAN` states.

## S4 — minimal scope

Planned minimal change:
1. add `scripts/release_gate.py` with pure validation/filter functions;
2. add `tests/test_release_gate_pr_scope.py` with negative tests;
3. modify only the evidence-selection block in the current `final-production-gate.yml`;
4. add a dedicated test step for `test_release_gate_pr_scope.py`;
5. do not replace the rest of the workflow;
6. keep branch `test_release_source_binding.py` additions outside this first patch unless independently required.

## S5–S7 — required tests and fail-closed behavior

Required before integration:
- [ ] helper unit tests pass;
- [ ] wrong PR number is rejected;
- [ ] wrong head SHA/ref is rejected;
- [ ] wrong base SHA/ref is rejected;
- [ ] PR evidence without PR association is rejected;
- [ ] wrong event is rejected;
- [ ] spoofed workflow name with attacker path is rejected;
- [ ] missing workflow path is rejected;
- [ ] unsafe or duplicate expected paths raise an error;
- [ ] invalid SHA and invalid event allowlist raise an error;
- [ ] current release-source contract tests continue to pass;
- [ ] workflow YAML remains parseable;
- [ ] missing or invalid evidence remains `missing`/failed and never becomes success.

## S8–S10 — boundary assessment

| Boundary | Assessment | Rationale |
|---|---|---|
| Authentication | UNCHANGED | helper filters metadata already retrieved by CI |
| Authorization | UNCHANGED | no application authorization path changed |
| Tenant isolation | N/A | release-evidence selector only |
| Human Gate | UNCHANGED | final manifest statuses remain unchanged |
| Evidence integrity | STRONGER | evidence identity includes PR/base/path binding |
| Provenance | STRONGER | workflow-run selection is tied to canonical identity |
| Replay | STRONGER/PARTIAL | stale/wrong run associations are rejected; runtime replay is out of scope |
| Secrets | UNCHANGED | no credential additions |
| Payments | N/A | no payment code change |
| Deployment | UNCHANGED pending workflow tests | gate selection changes only |
| Data/migrations | N/A | no schema or persistence change |

## Critical self-review

**Assumptions:** GitHub Actions run payloads used by the gate contain `path`, `pull_requests`, head/base SHA and refs in the forms expected by the helper.

**Missing evidence:** live fixture captured from the Actions API for both PR and main runs; actual CI execution of the integrated patch.

**Weakest evidence:** compatibility of every live Actions API payload shape with strict path/PR association filtering.

**Counterargument:** strict filtering may create false negatives if GitHub omits association/path fields in an otherwise valid run. The intended response is fail-closed, but operational availability impact must be tested.

**Worst case:** final production gate rejects all valid candidates or, if integrated incorrectly, filters after name selection and leaves the spoofing gap intact.

**Rollback:** revert the single salvage commit on the cleanup branch. No database or application-state rollback is required.

**Why minimal:** pure helper, focused negative tests and one integration point. No bulk branch merge and no replacement of the current production gate.

## Current verdict

`SALVAGE-PREPARED`, not `SALVAGE-VERIFIED`.

Promotion to `SALVAGE-VERIFIED` requires implementation on the controlled cleanup branch, targeted tests, post-write inspection, and CI evidence. Source branches remain retained until the full delete gate is rerun.