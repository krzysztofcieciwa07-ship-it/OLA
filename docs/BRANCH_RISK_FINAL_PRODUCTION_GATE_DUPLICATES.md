# Branch Risk Report: final-production-gate duplicate group

## Branches
- `fix/final-production-gate-20261006`
- `fix/final-production-gate-stage-20261006`

Shared tip: `9990e9f990cee87bc0d00c5c99566d4e436238f0`.

## Commit and reachability
The shared tip changes only `.github/workflows/final-production-gate.yml`. Default-branch commit search returns the exact commit, proving reachability from the default branch history.

## Current-main comparison
The tip adds the `push` trigger for `main` and event-specific filtering for required and reference workflow runs. Current `main` contains those same behaviors and a later expanded workflow with exact-source checkout, source-binding tests, evidence gate polling, image/source attestations, readiness verification and manifest publication.

Assessment: the shared-tip change is represented and superseded on current `main`.

## Dependencies
- `fix/final-production-gate-20261006` is associated with closed PR #62, `Fix and harden final production gate`.
- No PR was found for `fix/final-production-gate-stage-20261006`.

## Risk
- Code-loss risk: LOW.
- Workflow-loss risk: LOW; current `main` contains the relevant behavior in a broader workflow.
- Security/evidence risk: LOW; current `main` adds stricter source and evidence controls.
- Migration risk: NONE IDENTIFIED.
- Documentation risk: NONE IDENTIFIED.
- Historical-reference risk: LOW; PR #62 remains as the historical record.

## Disposition
Both branch references: `DELETE-VERIFIED`.

Delete branch references only. Do not remove the current `.github/workflows/final-production-gate.yml` and do not rewrite `main` history.
