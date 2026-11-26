# Branch Risk Report: source-binding duplicate pair

## Branches
- `fix/agent-runtime-source-binding-20261105`
- `verify/pr170-final-head-20261105`

Shared tip: `3f39ff8c1b705b501d86fcfa9572604596906e65`.

## Tip change
The shared tip modifies only `.github/workflows/state-continuity.yml`: on continuity runtime restart it passes the source/runtime commit into the container.

## Reachability
Default-branch commit search returns the exact commit. `REACHABLE`.

## Current-main comparison
Current `main` uses a stricter generalized source identity: `OLA_SOURCE_SHA` is derived from the PR head/current SHA, checkout is pinned to it, the image is built and label-checked against it, and both initial and restarted runtime containers receive `OLA_RUNTIME_COMMIT=$OLA_SOURCE_SHA` plus evidence-v4 key configuration. The original tip behavior is therefore represented and expanded on current `main`.

## Dependencies
- `fix/agent-runtime-source-binding-20261105` has historical closed draft PR #170.
- The second branch is explicitly a verification/final-head reference for PR170 and shares the exact same tip.

## Risk
- Code loss: LOW; workflow-only change.
- Test/evidence loss: LOW; current main has the continuity execution/checkpoint/restart verification and source binding.
- Security/provenance loss: LOW; current main's binding is stricter and uses exact source identity through build and runtime.
- Migration loss: NONE IDENTIFIED.
- Historical reference: preserved by closed PR #170 and this risk report.

## Disposition
Both branch references: `DELETE-VERIFIED`.
Delete references only; do not modify the current state-continuity workflow or rewrite `main` history.
