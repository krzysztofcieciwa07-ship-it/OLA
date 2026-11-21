# OLA — PR consolidation register

**Snapshot:** 2026-11-21  
**Repository:** krzysztofcieciwa07-ship-it/OLA  
**Main SHA at capture:** 8adf30cd5e41a18a5345f66e67f5ddcdbc164862  
**Mode:** Phase 0 scope freeze / consolidation only. No production/staging DB mutation, Railway change, secret change, merge, deployment or payment operation.

This register is a decision/navigation layer for existing PRs. It is not a substitute for current exact-SHA CI, an independent review, or the canonical task ledger. Every PR must be re-fetched before action.

## 1. Consolidation completed

### P0 writer-universe / infrastructure evidence package

**Canonical candidate: PR #272**

- URL: https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/272
- Base: main at 8adf30cd5e41a18a5345f66e67f5ddcdbc164862
- Head: 5f383614e01f93ac0db35511608658a796073ebf
- State: OPEN / DRAFT / mergeable
- Exact-head PR workflow runs: **14/14 SUCCESS**, 0 failures, 0 pending (captured 2026-11-21).
- Diff: 20 commits ahead of main, 0 behind; 12 files.
- Includes the former #269 API writer trace, #270 credential/rogue-writer source review, #271 external infrastructure evidence package, and #272 allowed-writer universe / path classification / offline telemetry correlation verifier and tests.

**Superseded PRs closed with explicit cross-reference:**
- #269 — closed; copied 'P0_WRITER_COVERAGE_API_ATOMIC_TRACE_2026-11-20.md' into #272.
- #270 — closed; source-only rogue-writer and credential/migration review is in #272.
- #271 — closed; external infra attestation/query package is in #272.

The historical commits and comments remain available. These documents remain source-only evidence: they do not prove production DB roles, IAM, firewall, backup, telemetry population, or live writer completeness. The operator evidence package in #272 is still outstanding. No application runtime code was changed in this consolidation.

## 2. Tenant-context / RLS consolidation — not complete

### Intended architecture

The uploaded full audit selects the order:
Evidence V4 writer coverage → trusted tenant context/RLS → OIDC identity → signed Human Gate → execution-bound approval verifier → report-review separation.

The selected PostgreSQL tenant design in PR #237's E2.2 architecture record is **Architecture C**: database-verifiable API-key / worker-claim / stored-checkout evidence; a protected transaction-local context; RLS calling a database-owned predicate; no authorization from caller-settable 'ola.tenant_id' GUC. Architecture B's signed GUC/HMAC prototype had a rollback/replay limitation. Architecture A has materially higher per-tenant credential/pool operations.

### Current PR dispositions

| PR | Disposition | Current finding | Required next step |
|---|---|---|---|
| #233 | 'HOLD / SUPERSEDE AFTER TRANSFER' | Earlier HMAC/GUC and initial E2.1/E2.2 exploration; 34-file wide diff, mergeable=false, old base SHA. | Preserve as history until Architecture C and needed tests exist on a current-main candidate. Do not merge. |
| #234 | 'EVIDENCE_ONLY / CLOSED PREREQUISITE' | Closed E2.1 worker schema/ACL prerequisite at '36cd93c...'. | Preserve source history; incorporate needed tests/logic into a current-main E2.2 candidate. |
| #237 | 'CANONICAL DESIGN CANDIDATE / BLOCKED REBASE' | Architecture C implementation, checkout-context binding/test now ported from #244, and ACL empty-array normalization. Current head '60d59508431a4ce66bf94ce7185e7f5e196ec406'; base main '8adf30c...'; GitHub reports 'mergeable=false'. It was originally based on E2.1 SHA '36cd93c...'. | Reconcile with main's later Evidence V4 changes before any merge. Exact diff from E2.1 base to main shows main changed 'app/database.py', 'app/main.py', 'app/paid_order_execution.py', PostgreSQL tests and related runtime/workflow files. Do not overwrite these newer changes with the older branch versions. |
| #244 | 'EVIDENCE_ONLY / PORT GAPS BEFORE CLOSE' | Divergent implementation branch based on #233. Its checkout binding and test were ported to #237. It also has 9 additional tests and helper implementations not yet present in #237. | Port/reconcile its unique protections/tests only after adapting to current Evidence V4 main; then close #244 as superseded only after exact diff and test coverage confirm no unique capability remains. |

### Known missing transfer from #244 to #237

The following 9 tests exist in #244 but not in #237:
1. 'test_role_membership_diagnostic_includes_grantor_and_admin_option'
2. 'test_provider_managed_migration_membership_is_narrowly_allowlisted'
3. 'test_runtime_refuses_a_migration_dsn_but_migration_mode_can_use_it'
4. 'test_postgres_verifier_rejects_role_name_collisions_before_database_access'
5. 'test_database_auth_context_rejects_malformed_evidence'
6. 'test_railway_worker_rejects_sqlite_and_requires_isolated_postgres_claim_url'
7. 'test_worker_identity_allows_only_neon_non_settable_admin_membership'
8. 'test_railway_worker_requires_shared_pepper_for_keyed_evidence'
9. 'test_worker_verifies_runtime_database_before_worker_claim_database'

The corresponding helpers are also missing from #237's current branch versions:
- 'app/database.py': '_format_role_membership_violations', '_role_membership_violations', '_assert_no_runtime_migration_url'
- 'scripts/run_paid_order_worker.py': '_validate_worker_database_mode', '_worker_role_membership_violations', '_validate_worker_evidence_key', '_verify_worker_connections'

Do not simply copy the old #244 files: the current main has since added Evidence V4 writer/verifier behavior. These helpers and tests must be ported into the current-main architecture, preserving V4 and exact current worker behavior.

**Safe current status:** #237/#244/#233 are all still open (except #234 which is closed); #237 and #244 remain Draft. No one is approved to merge this family yet. No database migration or test against shared/production staging has been run.

## 3. Current PR triage

Triage is a recommendation for the next review queue; it does not mean the PR has been closed or approved.

| PR | Proposed disposition | Reason / action |
|---|---|---|
| #276 | KEEP / review first | OIDC Subject verifier foundation; exact head must be revalidated and independently reviewed. |
| #280 | KEEP / stacked on #276 | Signed Human Gate contract and Ed25519 verifier; do not retarget or merge until #276 has been reviewed/integrated and #280 is rebased. |
| #272 | KEEP / consolidated writer audit | 14/14 exact-head workflow SUCCESS; still Draft and requires independent review plus external infrastructure attestations. |
| #277 | KEEP / documentation | Operational handoff and open-work snapshot. Snapshot is metadata-only and must be refreshed. |
| #237 | KEEP / BLOCKED REBASE | Architecture C tenant isolation candidate, but stale against main and mergeable=false. |
| #244 | EVIDENCE_ONLY / HOLD | Preserve unique tests/helper evidence while #237 is reconciled; do not merge separately. |
| #233 | SUPERSEDE AFTER TRANSFER | Old HMAC/GUC variant and wide branch; no closure until all required Architecture C evidence is preserved. |
| #275 | MERGE CANDIDATE AFTER REVIEW | Small Evidence V4 CI trigger change; compare against current workflows and check exact SHA. |
| #250 | MERGE CANDIDATE AFTER REVIEW | Evidence V4 cutover/readiness hardening; verify exact head, migration, replay and backward-compatibility tests. |
| #274 | HOLD | Tenant-scoped run filter depends on trusted tenant context and API contract freeze. |
| #268 | HOLD | Operator panel waits for stable health/evidence API contract. |
| #273 | EVIDENCE_ONLY / HOLD | Capability voucher / MockExecutor prototype; no real execution authority until scope/expiry/replay/policy broker is enforced. |
| #262 | HOLD / CONSOLIDATE LATER | Large 34-file watchdog/attestation workflow PR; do not merge before workflow matrix and trigger/permission/failure-mode inventory. |
| #267 | DEFER | Evidence parse/keyring optimization is not a release blocker; avoid perf changes during security boundary integration. |
| #246 | HOLD / REBASE REVIEW | CodeQL policy PR is based on the old #233 branch; do not merge that branch into main without rebasing onto current security workflow state. |
| #108 | EVIDENCE_ONLY / RECONCILE | Old continuity-ledger Draft based on historical main SHA; use #277 handoff and existing automation until ledger is rebased and reconciled. |
| #160 | HOLD / SOURCE DEPENDENCY | Vantage signed execution integration is stacked on old operator flow; wait for canonical Vantage decision interface and current-main rebase. |
| #252 / #256 | HOLD / STACKED | Vercel Sandbox adapter and planner hardening; preserve stack relationship, prove bounded sandbox and source digest before considering merge. |
| #148 | HOLD / STALE BASE | Non-mergeable old CI/auth fixture branch; compare with current main; likely superseded by later Python CI and fixture work, but do not close without diff check. |
| #214–#222 | DEPENDENCY REVIEW QUEUE | Dependabot updates; evaluate as a batch after package source-of-truth/lock strategy is agreed, with exact-source tests and compatibility. |

**Older open PRs:** Any PR based on historical October SHA/branch or with large stacked dependency chains stays 'UNKNOWN / REVIEW REQUIRED' until per-file diff and supersession mapping are checked. Do not bulk-close by title or age alone.

## 4. Backlog consolidation and ownership

Primary current GitHub blockers remain:
- #150 — effective main governance and independent review.
- #158 / #153 — durable production hosting, release acceptance and full E2E.
- #172 — separation of admissibility, execution authority and closure.
- #20 / #22 — real provider proof; no real OpenAI proof until exact run and approved secret path.
- #24 — paid path remains sandbox until separately authorized live transaction.
- #161 / #162 — canonical Codex Bridge / NOVA source and runtime not confirmed.

Open issue housekeeping (duplicate NOVA #165–#167, placeholder #128, miscellaneous stale items) is P2. Do not spend time on issue cosmetic cleanup before P0 governance, tenant/RLS and Evidence V4 consolidation.

## 5. Rules for the next consolidation passes

1. No new branch/PR while a candidate in the same domain can be reused.
2. Before closing any PR as superseded: compare its full diff; identify all unique files/logic/tests; transfer required material; record the new canonical PR; only then close with a cross-reference comment.
3. Before retargeting an old PR to main: inspect every file changed by both the PR and current main since its base. 'mergeable=false' or 'diverged' is a hard stop, not an invitation to use force.
4. Do not copy old full files across the current main's Evidence V4 changes. Use focused three-way port and exact-source tests.
5. No merge until independent review, exact-SHA required checks and governance are effective. Current main reports 'protected=false'.
6. Staging CI must use disposable PostgreSQL only. No production or shared staging database writes/migrations.
7. Report code/test proof separately from deployed DB, IAM, network, storage and production proof.

**Current decision:** writer audit package is consolidated into #272; tenant-context is NOT yet safely consolidated. Production remains NO-GO.
