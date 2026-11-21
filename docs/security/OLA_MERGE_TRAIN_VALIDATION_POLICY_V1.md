# OLA Merge Train — Priority-Based Validation Policy v1

**Policy ID:** OLA-MERGE-TRAIN-PRIORITY-V1  
**Effective snapshot:** 2026-11-21  
**Repository:** krzysztofcieciwa07-ship-it/OLA  
**Canonical implementation branch:** `docs/ola-operational-handoff-20261121` (PR #277)  
**Main SHA at snapshot:** `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`

This policy makes priority part of every validation result. A green CI run is evidence for the checks that actually ran; it is not automatically a PASS for a wider security or release invariant.

## 1. Result contract

Every gate MUST be recorded as one of:

- `PASS` — the defined acceptance criteria were executed against the exact identified source and all assertions passed.
- `FAIL` — one or more assertions failed, an invariant was violated, or forbidden behavior was observed.
- `UNKNOWN` — evidence is absent, stale, skipped, not independently verifiable, bound to another SHA/environment, or insufficient to establish the criterion.
- `NOT_APPLICABLE` — permitted only with a written scope reason. It must never be used to hide missing evidence.

Every recorded result MUST carry:
1. Gate ID and priority.
2. Exact candidate source SHA.
3. Test/workflow run ID(s) and conclusion(s).
4. Artifact/evidence reference and its source/environment.
5. Evaluator and evaluation timestamp.
6. Decision and remaining limitation.

**Skipped, missing, timed-out, stale-SHA or unexecuted checks are not PASS.** A source-level inspection is not live production attestation. A passing unit test is not a passing production gate.

## 2. Priority semantics and merge-train control

### P0 — CRITICAL / trust and security boundary

Any P0 `FAIL` OR `UNKNOWN` causes **IMMEDIATE STOP of the merge train**. Do not merge the affected candidate or any later candidate in the dependent train. Do not bypass, waive, relabel, downgrade or convert UNKNOWN to PASS. Resume only after remediation and a new exact-SHA validation proves PASS.

P0 controls are global trust invariants where the affected system surface is shared. A demonstrably independent change may be prepared in a separate branch while the train is stopped, but it must not be merged into the blocked release path or promoted as an RC.

### P1 — HIGH / release blocker

P1 `FAIL` or `UNKNOWN` blocks **Release Candidate creation/promotion and production release**. A technically independent merge may continue only if it does not depend on, weaken, or obscure the unresolved P1 control. Record the dependency and retain the RC block.

### P2 — NORMAL / maintainability

P2 `FAIL` creates a remediation item with owner, severity, and due condition. It does not block an independent merge unless review demonstrates that the defect changes a P0/P1 invariant; in that case escalate the gate before continuing.

### Escalation rule

Priority attaches to the **invariant and observed effect**, not permanently to the PR number:
- P2 presentation bug → remains P2.
- UI displays VERIFIED/HEALTHY while backend is UNKNOWN/BLOCKED → escalate to P1.
- Any cross-tenant data access, forged trusted context, accepted tampered evidence, forged/replayed approval, or false verified source identity → P0.
- An optimization that changes canonicalization, signature checks, key selection, tenant scope, replay handling, or failure semantics is not P2; escalate to P0 review.

## 3. P0 validation gates — mandatory STOP controls

| Gate | Invariant | PASS criteria | FAIL / UNKNOWN trigger |
|---|---|---|---|
| P0-01 Evidence integrity | Evidence authenticity, order and monotonic format policy are cryptographically enforced. | Tampering, wrong predecessor, wrong/unknown key, forbidden downgrade and unauthorized producer are rejected; valid records verify; negative paths run on the exact SHA. | Any malformed/tampered evidence is accepted; downgrade or producer boundary can be bypassed; a required negative path is skipped or unproven. |
| P0-02 Writer boundary | All production Evidence writes use an authorized, tenant-scoped, atomic V4 write path. | Exhaustive writer inventory covers app, worker, webhook, business, script, CI and infrastructure paths; each production writer is classified and proven authorized; no reachable rogue/raw writer; locking, append-only enforcement, commit/rollback and telemetry semantics are verified. | Any reachable unapproved writer; incomplete writer inventory; missing caller/transaction proof; no telemetry correlation where required. |
| P0-03 Tenant isolation | Tenant A and B cannot read or mutate each other's records. | Explicit matrix: A→A ALLOW; B→B ALLOW; A→B DENY; B→A DENY. Cover SELECT/INSERT/UPDATE/DELETE, joins, API paths, worker paths, and connection-pool reuse/commit/rollback on disposable PostgreSQL. | Any confirmed cross-tenant access or write; required path/table/pool state untested or UNKNOWN. |
| P0-04 Trusted Tenant Context | PostgreSQL tenant authority is derived only from database-verifiable authentication evidence, never caller-controlled context. | API-key fingerprint, database-issued worker claim, and exact persisted order/Checkout Session pair are independently checked; transaction-local trusted context is protected, tenant-bound, single-context, cleared on completion, and fail-closed when missing; RLS uses DB-owned predicate. | Caller can expand trusted tenant scope; forged/settable GUC grants access; missing/stale/replayed evidence obtains context; context leaks across transactions; any required path is UNKNOWN. |
| P0-05 Identity/OIDC | Only a bounded, verified identity assertion may enter the trusted identity path. | PR #276 verifier enforces configured issuer/audience, RS256 signature with bounded allowlisted HTTPS JWKS, required claims, size/host/redirect/algorithm/key constraints, and no token/claim logging. Integration separately proves tenant membership, role and identity separation; missing mapping fails closed. | Invalid/missing identity gains trust; untrusted JWT role claims authorize; network/JWKS bounds are bypassed; verifier or membership binding remains unproven for the protected flow. |
| P0-06 Signed Human Gate | Approval is authentic, human-originated, current, scoped to one exact effect and non-replayable. | Signed record binds tenant, operation, nonce, action/resource/request/effect digests, author/reviewer/principal and membership version, step-up metadata, exact policy/source/evidence tip, issue/expiry, and OPEN closure states. Current membership/signature/policy/source/evidence/target are rechecked at effect boundary; nonce + single outbox effect are atomically consumed; role separation and no self-approval are enforced. | Approval can be replayed, transferred, widened, self-approved, forged, signed by untrusted key, used with stale evidence/policy/source, or interpreted as proof of execution/closure. Offline schema/crypto tests alone do not prove application integration. |
| P0-07 Exact source SHA | Tested, built, and attested artifacts represent the same immutable source. | `expected_source_sha = tested_sha = build_source_sha = attested_source_sha`; each comparison has immutable recorded evidence. Any deployment/runtime reports the same image digest and source revision. | Any SHA/digest mismatch, mutable/unbound source, missing attestation or UNKNOWN comparison. |
| P0-08 Negative-path behavior | Uncertainty and errors never become authorization or success. | UNKNOWN/malformed/unverifiable remain BLOCKED/UNKNOWN; ERROR stays failure; missing/skipped check never becomes PASS; replay, invalid signature, tenant mismatch, invalid policy and absent evidence are rejected. | UNKNOWN→VERIFIED, ERROR→PASS, missing check→PASS, exception swallowed, stale result reused, or negative path not tested. |

## 4. P1 release gates — mandatory before RC

| Gate | Invariant | PASS criteria | FAIL / UNKNOWN consequence |
|---|---|---|---|
| P1-01 External attestation | Production claims are backed by evidence from the actual external environment. | Authorized operator provides redacted, timestamped and source-bound attestations for DB identity/effective grants/ownership/triggers, IAM and secret scopes, network/TLS, migration authorization, backup/restore, host/runtime identity and independently sampled telemetry as applicable. | Source docs or CI assertions are presented as live infrastructure proof; required external evidence absent. Block RC. |
| P1-02 Governance | Merge/release path enforces required reviews, checks and anti-bypass controls. | Effective main ruleset/branch protection is read back from GitHub; independent review is enforced; required status checks are bound to exact SHA; bypass/admin paths are documented and tested. | Only a proposed policy/script exists; effective rules are unverified; required review/check can be bypassed. Block RC. |
| P1-03 Runtime/Staging | The required RC runtime works on the exact tested source. | Durable target, TLS, health contract, persistence, restart/rollback and mandatory E2E integrations work in isolated staging; no unit-test-only substitution. | Runtime unavailable, non-persistent, health false, integration missing, or environment/source mismatch. Block RC. |
| P1-04 NINA sandbox | Planner output and execution are bounded and truthfully validated. | Strict schema, unknown-field rejection, bounded output/resources/time/network, sandbox identity, timeout/cancellation and independent outcome verification pass malformed/failure/hostile cases. | Malformed or forbidden output is accepted, sandbox escapes bounds, or tool output alone is represented as verified success. Block RC. |
| P1-05 Panel truthfulness | Operator UI faithfully represents backend truth. | Backend UNKNOWN→UI UNKNOWN; BLOCKED→BLOCKED; FAILED→FAILED; VERIFIED only when backend has a current independently verified PASS and matching source/evidence. | UI shows HEALTHY/VERIFIED while backend is UNKNOWN/BLOCKED/stale/missing. Block RC; treat misleading security status as P1. |

## 5. P2 quality gates

Naming, branch cleanup, non-semantic documentation duplication, metadata/catalog formatting, panel spacing/cosmetics and performance-only parsing/keyring optimizations are P2 only while they do not change a P0/P1 semantic boundary. Each P2 failure becomes a tracked remediation item. PR #267 stays P2 only after diff review confirms that canonical Evidence, key selection, signature, tenant and replay semantics are unchanged.

## 6. Ordered merge train (M1–M19)

The sequence is dependency order, not an automatic authorization to merge. Before every merge, evaluate all gate IDs touched by the change plus inherited upstream dependencies. After merge, re-read main SHA and re-run impacted source-bound checks.

| Stage | PR / scope | Priority | Required gate(s) | Continue rule |
|---|---|---:|---|---|
| M1 | #275 Evidence V4 CI trigger coverage | P0 | P0-01, P0-08; exact workflow trigger and negative-path execution proof | PASS required before M2 |
| M2 | #250 monotonic Evidence V4 cutover/readiness | P0 | P0-01, P0-07, P0-08 | PASS required before writer consolidation |
| M3 | Central Evidence writer (former #269, now included in #272) | P0 | P0-02 | PASS required before M4/M6 |
| M4 | Rogue Writer Hunt (former #270, now included in #272) | P0 | P0-02 | PASS required before M6 |
| M5 | External infrastructure attestation (former #271 package in #272) | P1 | P1-01 | May not block an independent technical merge; MUST PASS before RC |
| M6 | #272 writer universe + telemetry verifier | P0 | P0-02, P0-08, P0-07 for source-bound verifier execution | PASS required before PostgreSQL tenant gates |
| M7 | PostgreSQL RLS | P0 | P0-03 | PASS required before M8 |
| M8 | Trusted Tenant Context / Architecture C | P0 | P0-04, P0-03 | PASS required before M9 |
| M9 | #276 OIDC verifier and protected identity integration | P0 | P0-05, P0-08 | PASS required before M10 |
| M10 | #280 Signed Human Gate | P0 | P0-06, P0-05, P0-08 | PASS required before M11 |
| M11 | #274 tenant-scoped Evidence API | P0 | P0-03, P0-04, P0-08 | PASS required before release integration |
| M12 | OCI digest / source attestation (#227; source-image binding #192) | P0 | P0-07 | PASS required before M13 / RC build |
| M13 | #262 exact-SHA watchdog, attestations and CI alerts | P0 | P0-07, P0-08 | PASS required before RC validation |
| M14 | #254 governance | P1 | P1-02 | PASS before RC |
| M15 | Decision Charter / DORA (#228/#230) | P1 | P1-01, P1-02, P1-03 according to claims | PASS before RC |
| M16 | #268 operator panel | P1 truthfulness; P2 UI | P1-05 | P1 PASS before RC; P2 cosmetics may follow |
| M17 | #252 NINA sandbox adapter | P1 | P1-04, P0-08 where execution authorization is affected | PASS before RC |
| M18 | #256 sandbox output/planner hardening | P1 | P1-04, P0-08 | PASS before RC |
| M19 | #277 operational handoff | P2; false security claim escalates P1 | Accuracy against all current gate records | P2 before release docs; any false security assertion escalates to P1 |

### Consolidation mapping

The former #269, #270 and #271 PRs are closed as superseded and are not merge stages any longer. Their content is inside the single Draft PR #272. M3/M4/M5/M6 are therefore validation sub-stages of #272, not four separate merges. The #272 CI green state is only the CI sub-gate; the external writer/infrastructure assertions stay UNKNOWN until the specified evidence exists.

The tenant family remains blocked: #237 is the preferred Architecture C candidate but is stale/non-mergeable against current main; #244 retains unique DB/worker hardening tests/helpers not yet transferred; #233 is the earlier HMAC/GUC route. No P0-03/P0-04 PASS may be claimed until the current-main candidate preserves the Evidence V4 changes, unique required tests, and disposable-PostgreSQL negative/positive coverage.

## 7. Post-merge algorithm

After each proposed merge:

1. Read the new `main` commit SHA from GitHub.
2. Bind the merge commit to its exact PR head, review, required checks and merge commit.
3. Re-evaluate impacted gates and their downstream dependencies using the new main SHA; invalidate prior evidence if source changed.
4. Record each gate as PASS/FAIL/UNKNOWN with exact run/artifact references.
5. Apply the stop rules:
   - any P0 FAIL/UNKNOWN → STOP MERGE TRAIN immediately;
   - any P1 FAIL/UNKNOWN → block RC/release, independent non-dependent merges only may continue;
   - P2 FAIL → remediation item; continue only when no P0/P1 escalation exists.
6. Before RC: all required P0 PASS + all required P1 PASS + exact-SHA validation and health stability window PASS.
7. Only then record `RELEASE_CANDIDATE`; only exact-SHA final validation may advance it to `GO`.

## 8. Current evidence snapshot (2026-11-21)

All values below are an observation snapshot, not permanent PR status. Re-fetch the PR and exact commit before acting.

| PR / control | Exact SHA observed | CI observation | Review / integration observation | Gate result |
|---|---|---|---|---|
| #275 / M1 | `4cd0aea0364b7e22a3d924af850759c26b0b4c9a` | 22/22 workflow runs SUCCESS | Draft; no submitted PR review observed | CI sub-gate PASS; merge authorization UNKNOWN |
| #250 / M2 | `f2ca309047400cf68b7ed7f900923568a1afa404` | 22/22 workflow runs SUCCESS | Non-Draft; approvals present, but independence/effective main enforcement still must be established | CI sub-gate PASS; governance P1 UNKNOWN |
| #272 / M3–M6 | `5f383614e01f93ac0db35511608658a796073ebf` | 14/14 workflow runs SUCCESS | Draft; no submitted PR review; audit package is source-only; production writer telemetry/attestation not supplied | P0-02 UNKNOWN; P1-01 UNKNOWN |
| #237 / M7–M8 | `60d59508431a4ce66bf94ce7185e7f5e196ec406` | 16/16 workflow runs SUCCESS | Draft; GitHub mergeable=false; older than later Evidence V4 changes; #244 unique tests/helpers remain | P0-03 UNKNOWN; P0-04 UNKNOWN |
| #276 / M9 | `6bcc5fd66e21479c84ba62e17d02398f48d80d9c` | 22/22 workflow runs SUCCESS | Draft; no submitted PR review; verifier is not wired into approval/tenant membership flows | P0-05 UNKNOWN |
| #280 / M10 | `f210e7897dbe1aa80afcc4b915c7dc5e94acb6bf` | 17/17 workflow runs SUCCESS | Draft; no submitted PR review; offline contract only, no live signer/nonce/membership/routes | P0-06 UNKNOWN |
| #262 / M13 | `9d58e00a99d8ef23b555c14fb5d1b30a23d04864` | 22/22 workflow runs SUCCESS | Draft; 34-file integration; exact-source production/build attestation not established by source CI alone | P0-07 UNKNOWN |
| #227 / M12 | `5fe999467b26995c3ad9147f7a9952c33be52812` | Current exact-head CI not captured in this snapshot | Draft; base is historical main SHA `e0b5ca8...` | P0-07 UNKNOWN |
| #277 / M19 | `45afdee8e66fbd484ea2cc92643ccf1b5126fc35` | 16 SUCCESS; 4 IN_PROGRESS at observation | Draft documentation PR | P2 documentation status OPEN |
| Main governance | `8adf30cd5e41a18a5345f66e67f5ddcdbc164862` | GitHub branch endpoint reported `protected=false` | Effective independent-review/required-check enforcement not verified | P1-02 UNKNOWN |

**Current train decision: STOP.** At minimum P0-02, P0-03, P0-04, P0-05, P0-06 and P0-07 remain UNKNOWN. Passing PR workflow matrices do not close those broader invariants. M1 and M2 have green exact-SHA CI sub-gates; this policy does not itself merge them or claim full P0 acceptance.

## 9. Safety boundaries

- No force-push, no silent branch retarget workaround, and no merge based only on green CI.
- No production/shared staging database writes or migrations; PostgreSQL security tests use disposable instances.
- No Railway, secrets, identity-provider, signer/KMS, branch-protection or billing mutations under this policy.
- Never manufacture approval, reviewer identity, external attestation, customer result or runtime proof.
- Security claims require an exact source/evidence reference and explicit PASS; otherwise report UNKNOWN.
