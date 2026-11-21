# OLA di-OS — operational handoff and evidence intake

**Snapshot:** 2026-11-21  
**Purpose:** one recovery point for the next operator/session: current authoritative refs, open release blockers, environment boundaries, missing evidence, dependency order and the exact inputs needed to continue without rediscovering the project.  
**Classification:** documentation snapshot; not a release approval, not a production attestation, and not a replacement task database.

## 1. Source of truth and rules for continuing

- Canonical repository: https://github.com/krzysztofcieciwa07-ship-it/OLA
- Default branch snapshot: main at SHA **8adf30cd5e41a18a5345f66e67f5ddcdbc164862** (observed 2026-11-21). GitHub commit API reports signature verification as valid.
- The continuity ledger implementation is **not yet on main**. PR #108 is still open/draft; its head is 7c031b40cbf21756520a2ad303da660779c48356 and its base is 1aadf7d2edc5abe345ec1d08a26d5331b51e5bc3. Its registry is only present on that PR branch. Do not assume a new session can read it from main.
- PR #108 adds .ola/continuity/registry.json, scripts/project_continuity.py, anti-replay tests, CI guard and project instructions. The registry explicitly says bootstrap inventory is incomplete and contains 10 initial tasks. It is a candidate task ledger, not a completed forensic history. Reconcile/rebase it against current main before adopting it as canonical.
- Existing runtime continuity is already implemented in main through scripts/state_continuity_runtime.py and .github/workflows/state-continuity.yml. Do not create a second runtime checkpoint store. The task ledger is a separate concern.
- A complete open GitHub issue/PR metadata snapshot is stored beside this file in GITHUB_OPEN_WORK_INVENTORY_2026-11-21.json. It is a navigation index only: open does not mean current, mergeable or approved. Always re-read the current head SHA, reviews and required checks before acting.
- Do not infer completion from an issue being absent from the ledger, from green CI on another SHA, from a draft PR, from source code alone, or from an environment being online.

## 2. Current operational verdict

**Release: BLOCKED / NO PRODUCTION GO.** The following are independently observable blockers, not one generic failure:

1. Effective main governance is not enforced. Branch API reports protected=false and required status-check enforcement=off. Active ruleset 25853037 (“SECURITY.md”) contains only deletion and non_fast_forward rules and has no branch include scope. It does not require an independent review or CI checks.
2. No OLA FastAPI API/worker exists in the Railway project named “Ola di-os” production environment. That project currently contains n8n, Postgres and evolution-api. A Postgres service being present does not prove that the OLA application uses it.
3. The separate “OLA FastAPI Staging” project contains API and paid-order worker services, both online at 1/1 replicas during the 2026-11-21 read. Neither staging service has an attached persistent volume.
4. The staging API's latest deployment is from branch test/staging-panel-overlay-20261120-2052Z, SHA 151fe8684e7eaefffb6d29b611593d200f6ee8ca. The worker's latest deployment is from main, SHA 8adf30cd5e41a18a5345f66e67f5ddcdbc164862. These are not a same-SHA API/worker deployment.
5. OLA_DATABASE_URL exists in both staging services, but Railway returned variable names only / values redacted. The actual project/branch/database identity cannot be inferred. Do not request, print or paste the DSN.
6. The scheduled Supply Chain Evidence Gate run 44900512969 failed on main SHA 8adf30cd5e41a18a5345f66e67f5ddcdbc164862. The Gitleaks artifact is #14705294063. The recorded scan found 23 findings; each finding still requires individual classification. This does not, by itself, prove that a live credential was exposed.
7. OIDC verifier foundation PR #276 is draft and has no review. It returns a verified issuer/subject/tenant tuple but does not establish tenant membership, an authorized role or permission to approve.
8. Real OpenAI execution and a real customer payment remain unproven. An Ollama/deterministic result is not evidence of an OpenAI call; synthetic Stripe tests are not revenue.
9. The source/service identity for NOVA and the canonical Codex Bridge remains unconfirmed in issues #162 and #161 respectively.
10. User-supplied task UUID 2f7d3330-0720-4b79-b00a-2e3bd9532b94 remains unresolved. Previous broad read-only searches found no persisted match. The next useful source is the original /nina-run response or client-side request log, not another identical full scan.

## 3. Environment inventory — do not mix staging and production

### Railway project: OLA FastAPI Staging

- Project ID: 06e1fb77-5c6c-45f4-86a3-70423b09c648
- Environment: staging
- Environment ID: 49e9669f-ac25-41a1-a366-1fc458c73484
- API service: ola-fastapi-api / 23f2097d-d99a-46e2-9b5a-7ff57c803fb7
- Current Railway deploy ID: 7d166aec-5c5c-45f2-ad41-a6b5a5993f65 — SUCCESS — source SHA 151fe8684e7eaefffb6d29b611593d200f6ee8ca — branch test/staging-panel-overlay-20261120-2052Z
- Worker service: ola-paid-order-worker / 8dfa21a9-c35c-4b9e-ad24-338fe8470216
- Current worker deployment: 4ef6b5a1-930d-466e-bcd7-3344e03d5f55 — SUCCESS — source SHA 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 — branch main
- Last health read: both services online, 1 running replica each, no recent failures/critical/warning notifications in the 24-hour window, no pending staged changes.
- Attached persistent volumes: none on either service.
- OLA_DATABASE_URL and OLA_DATABASE_MIGRATION_URL are present by variable name on API; OLA_DATABASE_URL is present on worker. Values are redacted and must remain secret.

### Railway project: Ola di-os (production environment)

- Project ID: d85ed597-09aa-45dd-935f-a2d3a9410e2d
- Environment: production / 92baf1d5-e9ed-493c-92bb-06baa2e880e9
- Services observed: n8n, Postgres, evolution-api. Each currently has one replica and a 500 MB attached volume.
- No ola-fastapi-api or ola-paid-order-worker service is present in this project/environment.
- The Postgres service is not proven to be the database used by the staging FastAPI services. Do not assume the two Railway projects are connected.

**Required decision before production work:** explicitly designate the production target project/environment/service and database. Do not promote the current staging API or the existing n8n/Postgres/evolution services by inference.

## 4. Workstream register and required closure evidence

The following is the operational index. It complements, and must later be reconciled into, PR #108's task registry. Do not create parallel implementations for these workstreams.

| Workstream | Priority / state | Existing source | Next action | Objective DONE evidence |
|---|---|---|---|---|
| Release hosting and 10/10 acceptance | P0 / BLOCKED | Issue #158, #153; Railway inventory above; PR #271 | Select the intended production host and collect live infrastructure attestations. | Public/private production API on the approved target; TLS, network/IAM, persistent storage, backup and independently executed restore, external /readyz, alarms and rollback all bound to one release SHA. |
| Main governance | P0 / BLOCKED | Issue #150; active ruleset 25853037 | Owner/admin configures effective rules for main; this is not an agent-side change. | API/UI export shows correct refs/heads/main scope, independent approval, exact required checks, signatures per policy, no bypass/force-push; negative tests prove missing review/check blocks merge. |
| Database/runtime binding | P0 / UNKNOWN | Railway variable inventory; issue #158; PRs #269–#272 | Use a read-only identity query on the intended database and compare sanitized project/branch metadata with Railway references. | Sanitized proof binds API and worker to the intended database project/branch, effective roles, schema migration head, RLS and privileges. No DSN or credential value is disclosed. |
| Writer universe and telemetry | P0 / PARTIAL | PR #269, #270, #271, #272; issue #158 | Preserve stack dependencies; collect DB grants, triggers, function definitions and sampled DB/log correlation from the actual target. | Every permitted writer has an identified principal and path; unlisted writers are denied; sampled commits correlate to records and logs with bounded loss/timing policy; independent verifier reruns on hashed exports. |
| Supply-chain finding triage | P1 / BLOCKED | run #44900512969; artifact #14705294063 | Classify all 23 Gitleaks findings one by one; determine whether any value was live, test-only, generated or historical. | Per-finding disposition with path/commit/secret class, exposure assessment and proof. Confirmed credentials are rotated/revoked through owner-controlled secret management. No broad allowlist or unsupported false-positive declaration. |
| OIDC and approval authorization | P1 / OPEN | PR #276; issues #150/#158 | Finish CFR-2P-02 separately from the verifier foundation: bind a verified subject to persisted tenant membership and explicit role/approval policy. | Positive and negative tests prove wrong issuer/audience/tenant, non-member, wrong role, author self-approval and replay are rejected; authorized reviewer identity is recorded and independently verified. |
| Evidence semantics and IGOR | P1 / REVERIFY | PR #250, #267; issue #172; Evidence V4 code on main | Reconcile current V4 contract against existing v2/v3 migration history and IGOR verifier; do not rebuild hash-chain code. | Exact-SHA tests cover identity/type/tenant binding, mixed provider provenance, tamper, replay, append-only and deterministic replay; migration verified independently on a restored copy. |
| Real LLM provider proof | P1 / NOT PROVEN | Issue #20; runtime/source workflows | Identify the exact OpenAI workflow/job and ensure its provider credentials are configured through the secret manager, not chat or repo. | A completed run on the declared SHA records provider=OpenAI, model, invocation type, request/run correlation and output digest; independent verifier passes. Ollama proof remains a separate lane. |
| Revenue / paid execution | P1 / NOT PROVEN | Issue #24; issue #20; paid-order worker staging | After core E2E and identity gates pass, run an explicitly authorized low-risk LIVE transaction and follow it across the full path. | Real Stripe LIVE session → verified signed webhook → payment_verified → idempotent order → worker execution → Evidence V4 record → customer deliverable/refund state, all correlated by stable IDs. Synthetic events do not count. |
| Codex Bridge | P1 / BLOCKED_SOURCE_NOT_IDENTIFIED | Issue #161; OLA PR #160 and Vantage PR #13 are prerequisites only | Identify the canonical Codex Bridge repository/package, digest, API and staging service; do not substitute a generic provider. | Signed per-action OLA operation_id authorization, tenant/action/source allowlists, sandbox boundaries, independent result signature and real HTTP negative/positive E2E. |
| NOVA | P1 / BLOCKED_SOURCE_NOT_IDENTIFIED | Issue #162; OLA PR #160 and Vantage PR #13 are prerequisites only | Identify the real NOVA backend, identity provider, data model and two-client staging endpoints. | Two distinct authenticated accounts, tenant membership, reconnect/ACK/retry/replay/wrong-tenant tests and signed metadata event bound to operation_id. No chat plaintext or keys in Evidence. |
| Decision and execution closure | P1 / REVERIFY | Issue #172 | Audit the existing Evidence Chain/Policy Gate/Human Gate before implementation. | Admissibility, execution authority, execution observation and operational/epistemic/remedial closure are separate fields/states; UNRESOLVED cannot authorize tools; replay is deterministic; append-only corrections preserve history. |
| Continuity/anti-duplicate guard | P0 / PARTIAL | PR #108; existing runtime continuity files on main | Rebase/reconcile PR #108 on current main, merge only after current exact-SHA CI, independent review and governance are effective; manually apply Project instructions in ChatGPT. | Registry is on main, bootstrap inventory is reconciled or remains explicitly incomplete, CLI and anti-replay CI pass on the merged SHA, and a new session can find the registry without chat-history archaeology. |
| Unknown task UUID | P2 / WAITING_USER | UUID 2f7d3330-0720-4b79-b00a-2e3bd9532b94; original API call is absent | Recover the original /nina-run JSON response, caller log or downloaded run artifact. Do not repeat the same full scan without new evidence. | UUID is mapped to task_id, run_id, persisted evidence, or explicitly confirmed as an unpersisted planner task by the original response and source code path. |

## 5. Candidate PR map — current heads observed 2026-11-21

These are candidate diffs, not accepted releases. Exact heads must be refreshed before any review or merge.

| PR | Head SHA | Base SHA / dependency | Scope |
|---|---|---|---|
| #276 | 6bcc5fd66e21479c84ba62e17d02398f48d80d9c | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Bounded OIDC Subject verifier foundation |
| #275 | 4cd0aea0364b7e22a3d924af850759c26b0b4c9a | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Evidence V4 CI gate trigger coverage |
| #274 | 785ce8a77a35d9806afbae5da8241683e672b0eb | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Tenant-scoped evidence run filtering |
| #273 | 828450cf54e9f1656476f6ec8529929643b83b07 | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Capability voucher / MockExecutor prototype |
| #272 | bf1f7d086138f0576ba7f5e17bfb5d1cdb3fd05a | stacked on #271 head 46f3399b3c4b5edb17820b3d229d4c5fd8386b08 | Writer universe and telemetry verifier |
| #271 | 46f3399b3c4b5edb17820b3d229d4c5fd8386b08 | stacked on #270 head dbb6e77ed74e87e0242dc119179f098294011bf2 | External infrastructure attestation package |
| #270 | dbb6e77ed74e87e0242dc119179f098294011bf2 | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Rogue writer hunt |
| #269 | fc05cc64b19da0316388e6194c0ef71973e3789b | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | POST /evidence and central writer trace |
| #268 | 85ebc04fb7337888c810b158b10128735a752162 | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Panel health and tenant evidence ledger |
| #267 | 1dbd06474ead213475cd058f7c036a2e70afaaad | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Evidence verification parse/keyring reuse |
| #262 | 9d58e00a99d8ef23b555c14fb5d1b30a23d04864 | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Exact-SHA watchdog and attestation/CI alerts |
| #250 | f2ca309047400cf68b7ed7f900923568a1afa404 | main 8adf30cd5e41a18a5345f66e67f5ddcdbc164862 | Evidence V4 cutover/readiness hardening |

PRs #271 and #272 are deliberately stacked; #272 must not be treated as an independent main-based patch. Several older open PRs are stacked on historical bases. Do not bulk-merge, close or rebase them without comparing their exact diffs against main and one another.

## 6. Evidence intake checklist — collect once, attach to the matching workstream

- [ ] **Owner/admin — GitHub governance:** export/screenshots of effective main ruleset and branch protection, including exact branch scope and required check contexts; record the negative-test result.
- [ ] **Infrastructure owner — production target:** confirm Railway project/environment/service IDs that will host OLA FastAPI and worker, deployment source SHA, region, service identity, private/public ingress and domain.
- [ ] **Infrastructure owner — persistence:** identify the production database/storage binding by project/branch/resource IDs only; provide migration head, effective DB role, RLS/ACL evidence, backup schedule, restore run and measured RPO/RTO. Never attach connection strings.
- [ ] **Infrastructure owner — TLS/network:** provide DNS target, certificate chain/expiry, allowed ingress/egress, firewall rules, workload-to-database network path and time-sync status. Redact internal secrets and credentials.
- [ ] **Security owner — Gitleaks:** provide the complete 23-finding report in redacted form, each finding's commit/path/type classification, exposure assessment and rotation/revocation record where applicable.
- [ ] **Runtime owner — OpenAI:** provide exact workflow/run/job IDs, source SHA, sanitized provider/model/invocation metadata, verifier output and artifact digests. Never share API keys.
- [ ] **Payments owner — revenue:** provide an authorized test transaction reference, Stripe event/session IDs, order/run/evidence IDs and delivery result. Do not include cardholder data or secret signing keys.
- [ ] **Integration owner — Codex/NOVA:** provide canonical repo/package and source digest, service owner, staging URL/health receipt, auth model and a pair of test identities (no credentials).
- [ ] **Caller/session — UUID:** provide the original /nina-run response body or a sanitized request/response log containing the supplied UUID and timestamp.
- [ ] **Project owner — continuity:** review PR #108's registry against the current open-work JSON snapshot; manually copy the project instruction text into the ChatGPT Project only after the final policy is approved.

## 7. Dependency order

1. Preserve current main; reconcile the continuity-ledger branch and current open-work inventory. Do not let the task register silently replace source evidence.
2. Owner/admin closes effective main governance. Until then, no merge is treated as independently governed.
3. Designate the actual production backend/database target. Collect database and network identity before making any production change.
4. Complete writer-universe and telemetry attestation against the chosen target. Resolve supply-chain findings individually.
5. Complete identity/role/tenant authorization and policy/execution semantics. Keep Human Gate fail-closed.
6. Prove one exact-SHA full runtime with the real provider(s), then NOVA/Codex integrations using their canonical sources.
7. Prove the complete paid order path with an authorized real transaction.
8. Run the full 10/10 production acceptance in issue #158/#153, including backup/restore, external health, SLO, rollback and independent review.

## 8. Closure rules

Every evidence item must carry: stable task/workstream ID, source system, UTC capture time, exact source SHA or resource ID, environment, command/query or capture method, artifact URI, SHA-256 digest, redaction statement, verifier identity/result and known limitations.

Allowed states: TODO, IN_PROGRESS, BLOCKED, WAITING_USER, REVERIFY, VERIFIED. “DONE” is not a status synonym for “documented” or “tests passed”.

A workstream can move to VERIFIED only when:
- evidence is for the exact current source and intended environment;
- the independent verifier reproduces the claimed result;
- positive and negative paths meet the acceptance criteria;
- no unresolved human approval, identity, secret, persistence, monitoring or rollback gate is hidden;
- the result is recorded in the canonical task ledger after PR #108 is reconciled.

**Do not merge or deploy from this document.** It is a handoff and evidence collection index. Production remains BLOCKED until the release blockers above are closed with independent, same-release evidence.


## 9. Reusable intake worksheet

Use [EVIDENCE_INTAKE_TEMPLATE.md](EVIDENCE_INTAKE_TEMPLATE.md) for each artifact or capture set. It standardizes task/evidence IDs, UTC capture window, principal and environment, exact SHA/resource, capture method, export completeness, SHA-256, independent verification, redaction, runtime/database correlation, security impact and closure decision. Do not collect secrets or raw DSNs in the worksheet.


## 9. Consolidation update — 2026-11-21

The audit's Phase 0 scope-freeze is now being executed. The live PR inventory was refreshed after consolidation: **111 open PRs and 22 open issues**, from paginated GitHub REST results (100+11 PRs; 100+33 issue endpoint entries, with 22 actual issues after excluding PR objects). See 'GITHUB_OPEN_WORK_INVENTORY_2026-11-21.json'. This is metadata-only and must be refreshed again before later actions.

### Completed: writer/infrastructure audit consolidation

- PR #272 is the single Draft candidate, directly based on current main SHA '8adf30cd5e41a18a5345f66e67f5ddcdbc164862'.
- Head SHA '5f383614e01f93ac0db35511608658a796073ebf'; exact compare says 20 commits ahead, 0 behind and 12 files.
- Exact-head CI observed: 14/14 SUCCESS, no failures or pending checks.
- The #269 API-to-central-writer source trace was copied into #272.
- #269, #270 and #271 were closed with cross-reference comments as SUPERSEDED_BY #272. Their historical commits remain available.
- #272 remains Draft and source-only. It does not prove production DB writer completeness, live IAM, actual privileges, firewall/network, or production telemetry correlation. Independent review and external operator evidence remain required.

### Tenant/RLS: do not merge yet

- #237 is the preferred Architecture C design candidate and now includes the checkout-session database-context call/test ported from #244, plus normalization of empty function-ACL results.
- Current #237 head is '60d59508431a4ce66bf94ce7185e7f5e196ec406', base main '8adf30cd5e41a18a5345f66e67f5ddcdbc164862'; GitHub reports mergeable=false.
- Its original E2.1 base is '36cd93c85f0f78caa007feb33b59cb1286a17b40'. Current main contains later Evidence V4 changes, including updates to app/database.py, app/main.py, app/paid_order_execution.py and PostgreSQL tests. Do not copy old full files or force a merge.
- #244 contains nine additional DB/worker hardening tests and corresponding helper code not yet in #237. These include role-membership/admin-option validation, migration DSN guard, role-collision fail-closed behavior, malformed auth-context validation, worker DB mode/role/key checks and worker identity verification ordering.
- #233/#237/#244 remain HOLD. #233 is the earlier HMAC/GUC variant; #244 remains evidence for unique tests/helpers; #237 is preferred only at architecture level, not a merge-ready implementation. Do not close any of them until a current-main implementation preserves Architecture C, Evidence V4 and every necessary negative test on exact SHA.

### Active work priority

1. Keep main unchanged and production NO-GO.
2. Build a correct current-main three-way tenant-context integration; no force, no stale full-file copy.
3. Port and run the nine missing DB/worker negative tests on disposable PostgreSQL.
4. Independently review SECURITY DEFINER ownership/search_path/ACL/temp-table context, API-key/worker-claim/checkout bindings and V4 chain behavior.
5. Only then supersede #233/#244; run exact-SHA CI and request independent review.

Detailed PR decisions: 'PR_CONSOLIDATION_REGISTER_2026-11-21.md'.



## Checkpoint update — 2026-11-21, after main SHA b3c649f8412fee9b0554863a9bba60fbe7d01550

This supersedes the operational status above where it conflicts with later exact-source evidence; the original snapshot remains historical.

### Current P0 candidate state
- **PR #276 OIDC verifier foundation:** merged into main at `b3c649f8412fee9b0554863a9bba60fbe7d01550`. It verifies an OIDC subject tuple; it does not itself establish OLA tenant membership, role or Human Gate authority.
- **PR #280 signed Human Gate contract:** current head `1c8bfcfc0bc16fedcd6712f89a8d572c6c99d762`; 28 checks SUCCESS, 2 SKIPPED, 0 FAILED. Draft. Current review request accepted, but no current-SHA independent approval. Added semantic hardening for exact HTTPS issuer URLs, boolean membership-version rejection and controlled invalid decision types.
- **PR #273 capability-voucher prototype:** current head `6d8011717dd63c7df8442b5009f718ada6582aee`; 20 SUCCESS, 6 IN_PROGRESS, 2 QUEUED, 2 SKIPPED at this checkpoint. Draft. Includes bounded canonical JSON, verifier allowlist, issued/expiry checks, nonce-keyed replay and a local-file SQLite prototype. It is not wired into the shared runtime choke point and SQLite is not a production multi-host replay store.
- **PR #272 writer-universe / telemetry audit:** current head `5f383614e01f93ac0db35511608658a796073ebf`; 16 SUCCESS, 1 SKIPPED. Draft and source-only. Live DB grants, writer identities, network reachability, deployed schema and telemetry completeness remain unverified.
- **PR #274 tenant-scoped Evidence API:** current head `58941d249c843a585a326259a34fd1f46f86cc57`; 27 SUCCESS, 1 IN_PROGRESS, 2 SKIPPED. Draft. Run-filtered results are explicitly `run_subset` / `NOT_VERIFIED`; tenant scope remains enforced in the query.
- **PR #281 CI trigger reliability:** current head `3a354a6767d624c3007f609c81b6f636b6863a7b`; exact-head CI rerun is pending. Draft. It removes path filters from the PostgreSQL contract and protects main's Python CI from cancellation. PR #275 was closed as superseded by #281.
- **PR #277 handoff:** this file's previous main SHA, open-work snapshot and infrastructure inventory are historical; refresh exact state before relying on them.

### Effective governance and review access
- Main branch reports `protected=false`; required status-check enforcement is off. Ruleset 25853037 has only deletion/non-fast-forward rules and no effective main scope. Detailed classic-protection read remains 403.
- Current independent review is a HUMAN_GATE. The request on #280 was accepted. Requests on #272, #273, #274 and #281 returned GitHub 422 because the nominated reviewer is not a collaborator; a repository owner must nominate/add an authorized collaborator.
- No merge, deployment, production DB access, credential change or branch-rule change was made.

### Dependency order from this checkpoint
1. Current-SHA independent review and approval contract acceptance (#280); then tenant membership binding, role/revocation, nonce and expiry enforcement.
2. Integrate voucher/approval enforcement at one shared execution choke point; route protected execution paths through it; replace local SQLite replay with durable shared DB replay.
3. Reconcile writer universe and tenant isolation against actual infrastructure, including external DB/IAM/network attestations and zero-mismatch telemetry sample.
4. Sandbox/network allowlists, stress/recovery, supply-chain and reproducibility gates, effective branch protection, lifecycle audit, release manifest and full E2E.
5. Production GO remains blocked until all required exact-SHA and independent external proofs are present.
