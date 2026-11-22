# Issue #150 — Effective main governance evidence package

## Stable task manifest
- ID: OLA-GOV-150-2026-11-22
- Priority: P1 / security / human-gate:required
- Status: BLOCKED / HUMAN_GATE
- Owner: repository owner/admin; coordinator and independent verifier
- Dependency: Issue #296 independent CODEOWNER and PR #300 candidate policy
- Source: main SHA `911c1cedf76dc6139f57b5d893d708b1a92245c6`
- Evidence-only: no code or repository-setting mutation

## Exact read-back findings
1. Repository branch API reports `main protected=false`.
2. Ruleset #25853037 — `SECURITY.md` — is active, but `conditions.ref_name.include=[]` and `exclude=[]`; it does not scope to `refs/heads/main`.
3. The only stored rules are `deletion` and `non_fast_forward`; no required review, CODEOWNER review, check context, signature or main protection is established by this ruleset.
4. Ruleset #25853037 has no bypass actors and current_user_can_bypass=never; this does not compensate for the empty branch scope.
5. GET branch-protection for main returned 403 `Resource not accessible by integration`; effective branch-protection details are not independently read-back verified.
6. PR #300 candidate head `f57e3bbd819fab529ec8105f5d32ba23e84947ac` is DRAFT. Human Gate policy unit tests are SUCCESS; final-production is still IN_PROGRESS. Candidate workflow is not trusted on main until merged.
7. No independent write-enabled CODEOWNER is proven. No negative or positive enforcement test has been executed against effective main rules.

## Required owner/admin action
- Designate/add an independent collaborator with write/maintain/admin permission and CODEOWNER coverage for `*`, `/.github/`, `/scripts/`, `/app/`; the repository owner cannot satisfy independence.
- Configure an effective ruleset/branch protection scoped to `refs/heads/main`: at least one independent approval, CODEOWNER review, stale approvals dismissed, last-push approval, exact required checks (including `human-gate-approval`), signatures and no bypass actors.
- Configure the read-only fine-grained `HUMAN_GATE_GOVERNANCE_TOKEN` with Administration:read in the dedicated environment; do not expose its value. Missing/denied must remain BLOCKED.
- Read back stored and effective rules and run a negative test (unapproved/no-check PR blocked) plus a positive test (approved + exact required checks mergeable).
- Keep this issue OPEN until the evidence is captured and independently verified.

## Safety
No ruleset or branch-protection mutation, collaborator permission change, secret access, merge, production deployment or terminal effect was performed. This document is evidence only; it is not approval to activate governance.
