# CLN-001 Salvage Checklist

Use this checklist for every `SALVAGE-FIRST` item.

## Source and scope
- [ ] exact source branch and SHA frozen;
- [ ] no source mutation, bulk cherry-pick or merge;
- [ ] each salvaged symbol/section identified separately;
- [ ] threat/failure addressed is explicit;
- [ ] current-main equivalent evaluated.

## Classification
- [ ] security fix;
- [ ] regression test;
- [ ] fail-closed control;
- [ ] evidence/provenance;
- [ ] data integrity;
- [ ] CI/release safety;
- [ ] documentation;
- [ ] product feature isolated from cleanup.

## Negative comparison
- [ ] no stale architecture restoration;
- [ ] no newer control removed;
- [ ] Human Gate, tenant, evidence and provenance not weakened;
- [ ] no alternate runtime/persistence introduced;
- [ ] status semantics not promoted without evidence.

## Minimal design
- [ ] minimal patch preferred over cherry-pick/merge;
- [ ] test demonstrates missing protection before implementation;
- [ ] malformed/missing/wrong identity/SHA/branch/path/event cases covered;
- [ ] irrelevant cases marked `N/A` with rationale;
- [ ] failures remain block/review/error, never allow/verified.

## Boundaries
For each: `UNCHANGED`, `STRONGER`, `WEAKER`, `UNKNOWN`, or `N/A`:
- [ ] authentication;
- [ ] authorization;
- [ ] tenant isolation;
- [ ] Human Gate;
- [ ] evidence/provenance;
- [ ] replay/signatures;
- [ ] secrets/payments;
- [ ] deployment;
- [ ] data/migrations.

## Validation
- [ ] targeted new tests;
- [ ] related security tests;
- [ ] component regression tests;
- [ ] CI/release contract tests;
- [ ] post-write content verification;
- [ ] exact candidate-SHA CI evidence.

## Critical self-review
- [ ] assumptions;
- [ ] missing evidence;
- [ ] weakest evidence;
- [ ] counterargument;
- [ ] possible regression;
- [ ] worst case;
- [ ] rollback;
- [ ] why minimal;
- [ ] why the source branch can or cannot later be removed.

## Outcomes
`SALVAGE-VERIFIED`, `SALVAGE-PARTIAL`, `SALVAGE-BLOCKED`, `ALREADY-IN-MAIN`, `KEEP-BRANCH`, `SECURITY-HOLD`, `PRODUCT-SCOPE-HOLD`.

`SALVAGE-VERIFIED` never automatically authorizes source-branch deletion; rerun the full delete gate.