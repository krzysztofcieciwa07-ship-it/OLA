# Open PR Deep Review — 2026-11-09

**Status:** SELECTIVE DEEP REVIEW COMPLETE / PORTFOLIO TRIAGE STILL OPEN  
**Main baseline:** fe32bf8c9710c4c04308ad17f1876fa4f80c01a2  
**Governance branch head at review start:** f05906245adc38d66d9eb2fa172adad2947f83af  
**Scope:** targeted review of high-risk open PRs, current-main implementations, selected test files, GitHub Actions job logs, and read-only Vercel/Railway configuration and deployment metadata. This is not a diff review of all 77 open PRs.

## 1. Executive result

The 77-row CSV remains a historical triage snapshot. The following review is a separate, selective assessment of the highest-risk items. It distinguishes (a) a defect still present in current main, (b) a patch already superseded by another implementation, (c) a defect confined to an unmerged branch, and (d) an external control verified in a connected provider.

Highest-priority results:

1. **PR #190 has a confirmed OIDC Human Gate approval defect.** The OIDC identity is passed during preflight but omitted during the second locked validation. The OIDC_REQUIRED approval path therefore fails closed with HTTP 400 before an approval/outbox transaction is committed. The test suite has no positive OIDC approval test.
2. **PR #197's Certificate Apocalypse scenario is not runnable as currently wired.** CI fails because the host-side probe cannot resolve Docker-internal service DNS. Further deterministic failures remain behind that blocker: three containers are started while an assertion requires two, and the generated certificate SAN does not contain the TLS hostname.
3. **Two generic evidence-verification invariants remain incomplete in current main:** the generic hash-chain verifier does not enforce one tenant per supplied chain, and the IGOR verifier can match missing results as the string "None" and can combine provider/model/response IDs from separate provenance records. Normal call sites often tenant-filter records and the current NINA path writes one provenance record, so the direct exploit path is constrained; the helpers nevertheless do not enforce their own trust contract.
4. **Several older PRs should not be merged blindly.** Payment-session binding from #97 is already present in main. The old approval flows from #94/#98 have been superseded by the newer NINA workflow approval path. The PBKDF2 implementation in #95 has been superseded by a different scrypt verifier in main.
5. **Vercel SSO protection for the OLA revenue preview is verified, not unknown.** The actual #194 staging deployment belongs to the SSO-protected project and is protected for all deployments. This materially mitigates the previously raised public BFF concern.
6. **Railway staging is a real deployment, but its deployed revision is behind the current source revision and the latest deployment is sleeping.** The Railway source configuration identifies commit 393cc56dcd8c1a749cf11d4306d1e247144139cb; the latest deployment metadata identifies 030f7f1a4e18ba45da2cc9edbe530ffed92ee56. GitHub comparison shows the deployed SHA is three commits behind the PR #195 branch head. Do not treat the active source configuration as proof that the latest code is running.

## 2. Current-main findings that need fresh, focused remediation

### 2.1 Tenant identity is not enforced inside verify_chain()

**Current main:** app/hashchain.py, blob SHA f4944b6436f4530b22f9bd76c11881c5f67687a1  
**Candidate fix:** PR #91, head 543e4acc3a075e53ec999574b26a937e4b0eaba8

The current generic verify_chain() validates sequence continuity, predecessor hashes, V1/V2 digest calculations, and producer/type binding. It does not capture the first tenant ID and reject a later record whose tenant_id differs.

A correctly recomputed mixed-tenant sequence can therefore satisfy this helper's local chain checks. Most reviewed application call sites select records with a tenant_id filter before calling the verifier, and the newer DAG verifier also accepts an expected tenant. This limits the normal route exposure observed in this review; it does not make the generic helper's contract safe. A future caller can accidentally pass a mixed list and receive "ok".

**Disposition:** MEDIUM/HIGH integrity invariant gap in current main. Do not merge the old branch blindly; port the tenant invariant and regression tests onto the current main base, and add a test that constructs a correctly re-hashed cross-tenant list.

### 2.2 IGOR accepts an under-specified result and permits provenance splicing

**Current main:** app/igor.py, blob SHA 268f46c03f5a9340f758e21dab83626e501b01a4  
**Candidate fix:** PR #92, head 51ff6b3fe7ad5370d65e08e0db99bff15a7de2cc  
**Existing test file inspected:** tests/test_igor.py, blob SHA 0aeee6916e4530fe384da71027c55e95f34a0edb

The result comparison stringifies both sides. If expected_result is None and a privileged record has neither result nor tool_output, both stringify to "None", which can be treated as a match. In addition, provider, model and response IDs are checked across the set of provenance payloads rather than being bound to the same real-LLM invocation record.

The current main NINA caller normally supplies a string fallback and creates one provenance.runtime event for its run, so the reviewed route does not demonstrate a general remote exploit. The generic verifier still accepts a weaker evidence contract than its name implies. The existing tests cover clean runs, wrong commits, missing evidence, real Ollama provenance and run scoping, but not the missing-result or cross-record-splicing cases.

**Disposition:** MEDIUM verification-contract defect in current main. Port the #92 protections with tests for null/missing outputs and provider/model/response IDs split across records. Do not mark the verifier as fixed based on ordinary happy-path tests.

### 2.3 Public evidence write boundary: primary spoofing path blocked; payload bounds remain

**Current main:** app/main.py, blob SHA b936273f9723416cdec3cd9f7cbeff4a100bc7d8; app/hashchain.py as above  
**Candidate hardening:** PR #93, head d58199104e198cefab4ee5b95938deee98d366a6

The current /evidence route rejects privileged evidence type prefixes, rejects caller-supplied reserved V2 metadata, and writes with the public tenant_api producer. The hashchain binding then prevents a public producer from creating trusted privileged evidence. This means the core public-forgery concern from the old PR is materially mitigated in current main.

The inspected current route does not show the stricter record-type allowlist, reserved root-field rejection and explicit payload-size limit proposed by the old PR. That leaves namespace and resource-consumption hardening incomplete.

**Disposition:** PARTIALLY SUPERSEDED. Do not reapply the entire old patch without checking it against the current sealing contract. Add bounded payload size and an explicit public record-type policy on top of current main.

### 2.4 Old approval-flow PRs #94 and #98 are superseded by a newer workflow route

**Current main:** app/main.py blob b936273f9723416cdec3cd9f7cbeff4a100bc7d8; app/nina_workflow_gate.py blob fd7c10263920536713abb73e66a41547ae3c0220

The current API route /nina-workflow/{run_id}/approve calls approve_workflow(). It verifies the tenant-scoped chain and DAG evidence, requires a unique workflow plan, separates requester and approver identities, checks the independent IGOR report digest, rejects a second review of the same run, and rechecks the tip under a write transaction before appending the review-only approval. The recorded decision explicitly does not authorize production.

The current main implementation uses SQLite BEGIN IMMEDIATE. That is consistent with current main's SQLite-only database.py. The staging branch contains a later database abstraction: begin_write_transaction() uses SQLite BEGIN IMMEDIATE or a tenant-scoped PostgreSQL advisory lock. Its staging implementation uses that shared transaction function instead of the old SQLite-only check. Therefore the earlier suspicion that the active PostgreSQL staging route necessarily returns 503 is **not confirmed** for the staging branch; the newer staging implementation specifically addresses that backend difference.

**Disposition:** #94/#98 are OLD-FLOW / SUPERSEDED for the current main workflow route. Do not merge their historical candidate-route patches as-is. Keep a separate check that the PostgreSQL transaction implementation has concurrency tests against a real PostgreSQL instance.

### 2.5 PR #97 exact Stripe session binding is already present in current main

**Current main:** app/main.py blob b936273f9723416cdec3cd9f7cbeff4a100bc7d8; app/stripe_webhook.py blob daad2cf6da0718499f87130989635a9be6ece0df; tests/test_payment_session_binding.py blob 0b3647afe64b92f75ffd10696fe4ab598d1ebebc

The current success path binds the returned order/payment state to the exact Stripe checkout session and refuses a completed result associated with another session. A regression test covers two sessions, including cross-session/cross-tenant separation. This addresses the principal concern in PR #97.

**Disposition:** IMPLEMENTED IN MAIN / STALE OPEN PR. Do not merge the historical patch just to close the PR; compare it once more against main and then mark the old PR superseded through the normal owner/review process.

### 2.6 PR #95 PBKDF2 cutover was superseded by the current scrypt verifier

**Current main:** app/api_key_hashing.py, blob SHA 7100dcd3caedfc189b3b249b56c30d1003016224

The current main key verifier uses scrypt with a deployment-specific pepper requiring at least 32 UTF-8 bytes, bounded concurrent hashing and no legacy SHA-256 fallback. PR #95 contains an older PBKDF2-HMAC-SHA256 implementation and an offline SQLite reissue script. The old script is not suitable for the current PostgreSQL staging deployment.

The live production/staging pepper values, the state of any production key rotation and the credential inventory were not inspected or decrypted. A code implementation is not proof that an operator has completed customer key reissuance.

**Disposition:** DO NOT MERGE THE OLD PBKDF2 VERSION into the scrypt mainline. Treat operational key rotation as a separate deployment task requiring an approved database-specific migration, backup, customer distribution and rollback plan. Secret values were not read during this audit.

## 3. PR #190 — OIDC Human Gate and customer delivery

**PR:** #190, head fbe2a19dc6c0a2a948f0a311cd7f91b798b97e07, branch feat/oidc-human-gate-customer-bundle-20261107  
**Scope:** 73 files, 11,993 additions / 173 deletions  
**CI at inspected SHA:** 26 success, 3 skipped (oci-slsa-attestations, igor-independent, scorecard), 0 failed  
**Review evidence:** 38 review submissions, 37 APPROVED plus one bot COMMENTED. The 37 approvals are from one distinct human login, krzys167-crypto. The relationship/independence of that login from the connected account was not verified. These are not 37 independent reviewers.

### Confirmed functional blocker

- OIDC route in app/main.py (blob SHA 5cd1d84b9870b02c40c6682664b37dbad8c97c15) calls approve_paid_order() with approver_principal_id and approver_person_ref, with no legacy API approver_id.
- app/order_approval.py (blob SHA bccc21e64416c432147aa6b9655b728ec2d34fff) passes those OIDC fields into the read-only preflight validation.
- The second validation, inside the locked write transaction, calls _validate_paid_order() with only approver_id and tip_hash. It omits approver_principal_id and approver_person_ref.
- The OIDC branch therefore enters the legacy identity check with approver_id=None and raises HTTP 400 ("legacy API approver identity is required") before approval evidence and the execution outbox job are committed.

This is a fail-closed functional failure, not an authorization bypass. It prevents valid OIDC operators from approving paid orders.

### Test gap

tests/test_paid_order_approval.py (blob SHA d9f49c6afd3505109c44b29643a9e06ee688c25c) exercises legacy API-key paid-order approvals. tests/test_human_gate_paid_order_routes.py (blob SHA b785afbded3e28256643d769b46a2d48fad61dad) verifies that API keys cannot approve/review OIDC_REQUIRED orders, but does not prove that a valid OIDC operator can approve one successfully. The code path that fails is therefore not covered by a positive OIDC approval test.

### Required correction

Pass both OIDC identity fields through the locked revalidation exactly as in preflight. Add an end-to-end route test with an authenticated, fresh OIDC operator session, tenant match, role execution_approver, CSRF validation, distinct HR person_ref, valid payment evidence and a current chain tip. Assert one approval record and exactly one outbox job. Also verify that the worker binds the stored OIDC principal/person_ref to the approval record before dispatch.

### Production-delivery boundary

The PR itself correctly states that production IdP, HR/SCIM, KMS/HSM, TSA and storage are not selected or integrated. The inspected production customer-bundle runtime remains fail-closed when a production signer/provenance/timestamp/storage implementation is not injected. This is safe, but it means production customer delivery is not yet operationally proven. Development fixtures and local signing do not prove a real enterprise signing chain.

**Disposition:** HIGH PRIORITY / FIX BEFORE ACCEPTANCE. Draft must remain open until the OIDC approval test passes and the production delivery dependencies are explicitly implemented or scoped out of the offer.

## 4. PR #197 — Certificate Apocalypse / Chaos DSL v0

**PR head:** aac6a4e370152575fc569c9cf422e8d3033c5bd2  
**CI:** 19 success, 1 failed scenario check, 1 skipped independent check  
**Failed job:** https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/42564975624/job/128989413738

### Actual CI failure

The scenario schema passed validation. Docker Compose successfully started tls-target, control-sentinel and chaos-runner on an internal-only network. The host-side runner then invoked probe_tls.py with OLA_TLS_HOST=tls-target. The host could not resolve that Docker-internal service name: the job records target_error_type=gaierror and control_ok=false. The scenario aborted at the readiness stage. No probe/load/assertion report was created, and Actions warned that no report files existed to upload.

The runner uses host processes for Python probe and k6 while Compose defines the target and sentinel only on an internal Docker network with no published ports. Move the probe/load execution into a container attached to that network, or deliberately publish only loopback-bound ports and use a host-resolvable address. Do not weaken TLS verification.

### Deterministic blockers after the first network fix

1. Compose starts tls-target, control-sentinel and chaos-runner by default. assertions.py requires container_count == 2. The normal run will therefore fail this assertion after connectivity is fixed unless the expected resource set is corrected.
2. The generated leaf certificate SAN is DNS:localhost, DNS:tls-under-test and IP:127.0.0.1. The scenario target hostname is tls-target. Strict hostname validation will reject the certificate for the configured target name after network connectivity is fixed.
3. scenario.json declares anti_llm.private_assertion_policy=true, but the checks and assertions are in the public repository. A boolean policy flag is not a private assertion pack or a server-side hidden grader.
4. score.py records missing_evidence_files in the evidence manifest but does not fail merely because required evidence files are missing. The final pass/fail is derived from assertions and score, not manifest completeness.
5. Early readiness failure exits before the report directory is created; workflow artifact upload then has no run report. Preserve a failure bundle with Compose state, per-service logs, exact probe diagnostics and the run context even when the scenario aborts before normal assertions.

**Disposition:** FAIL / NOT RUNNABLE. Do not describe this scenario as a functioning chaos range or as anti-LLM/hidden-test protected until the network topology, expected container inventory, SAN and evidence-completeness checks are corrected and CI passes on an exact new SHA.

## 5. PR #198 — tenant-scoped Ed25519 Merkle checkpoints

**PR head:** 2b46a5cbd6acba718f9de88aeb9730ce44858883  
**CI:** 19 success, 2 failed Ollama runtime checks, 2 skipped checks  
**Review evidence:** 10 review submissions from one distinct human login, krzys167-crypto; independent status not established.

The reviewed implementation verifies the tenant evidence sequence, computes domain-separated Merkle leaves/nodes, signs a canonical manifest with Ed25519, and distinguishes a mathematically valid signature from a signer that is trusted by a pinned key. This is a sound prototype direction.

The docs explicitly limit the scope: no authenticated REST API, durable checkpoint scheduler, externally anchored prior-checkpoint chain or production key-management adapter is included. The record-loading helper filters by tenant but relies on its caller to authorize that tenant. These boundaries must remain explicit in product claims.

**Disposition:** PROTOTYPE / PARTIAL. No major bypass was confirmed in the reviewed files; production integration and trusted signer custody remain unimplemented.

## 6. PRs #194, #195, #191 and #192 — staging console, BFF, bootstrap and build identity

### Vercel control verified

Vercel project ola-di-os-revenue-preview (project ID prj_iK4J75zfF80Y3QWKGsggrrubhFIp) has SSO protection enabled for all deployments. The inspected #194 deployment dpl_Bg4xpkQdVpKMZDG338jGq9kt8dtC is a staging deployment built from the exact #194 head 957e1ba7f8bf40dabc27630f694ce3c6eafeeffc, with alias ola-di-os-revenue-preview-krzysztof-s-projects9ola.vercel.app. This corrects the earlier unresolved concern about whether the deployed BFF sits behind an external access gate.

Vercel variable metadata lists OLA_BFF_API_KEY as a sensitive Preview-only secret and OLA_API_BASE_URL as a Preview-only URL. Bootstrap variable metadata says the bootstrap secret/trigger were disabled after provisioning. Values were not decrypted. Metadata comments are not proof that a secret was erased.

The BFF code does not provide its own browser session authentication or rate limiting. The verified Vercel SSO is therefore an important external control. The Railway service hostname is separately public and does not inherit the Vercel project's SSO; direct backend access still relies on service/API-key controls.

### Railway staging observed state

- Project: OLA FastAPI Staging.
- Environment: staging, Europe West.
- Service: ola-fastapi-api.
- Configured source: krzysztofcieciwa07-ship-it/OLA, branch feat/ola-staging-bootstrap-20261108, configured source SHA 393cc56dcd8c1a749cf11d4306d1e247144139cb.
- Generated public hostname: ola-fastapi-api-staging.up.railway.app.
- One replica configured, no volume attached, application sleep enabled, tracing disabled.
- The pre-deploy command runs PostgreSQL migrations and verifies that the ola_runtime role has SELECT/INSERT but not UPDATE/DELETE/TRUNCATE on evidence_records. This is a positive least-privilege control.
- The latest deployment is SLEEPING with no active replica at the current poll; environment_status shows no pending work and no current Railway warning/critical issue.
- Historical HTTP logs show /_internal/staging/bootstrap-bff-key returning 201 once and 409 on later retries, followed by /nina-run returning HTTP 200. These are endpoint-level observations, not proof of a verified NINA result, a delivered customer report or stable availability.
- Historical deploy logs include a failed /readyz healthcheck at deployment 51ac1af5-2a8b-4d8d-9b49-056dfe049f91. The app started and logged OLA_POSTGRES_SCHEMA=VERIFIED, but the healthcheck received repeated service-unavailable responses and deployment failed. Later deployments were created; the latest is currently sleeping.

### Source/deployment SHA mismatch

The latest Railway deployment metadata identifies commit 030f7f1a4e18ba45da2cc9edbe530ffed92ee56. The current branch/PR #195 head is 393cc56dcd8c1a749cf11d4306d1e247144139cb. GitHub compare shows the deployed commit is the merge-base and is three commits behind the branch head. The Railway service configuration reports the newer source SHA, but the latest deployment metadata still identifies the older image source.

**Disposition:** STAGING ONLY / SOURCE IDENTITY RECONCILIATION REQUIRED. Before claiming the latest PR code is live, produce a new deployment whose metadata commit SHA exactly matches the approved target SHA, then verify /readyz over a stability window and run the staging BFF end-to-end with synthetic tenant credentials. No redeploy was triggered by this audit.

## 7. PR #193 — static revenue-preview headers

The PR adds CSP, HSTS, frame protection, MIME-sniffing, referrer and browser-permission headers, and short CDN revalidation. This is a static-site hardening change and does not enable Stripe checkout or a backend. CSP permits inline script/style for the current page; this is a residual hardening trade-off, not proof of compromise. The actual deployment is covered by the verified Vercel SSO project control described above.

**Disposition:** STATIC PREVIEW HARDENING / NOT A LIVE CHECKOUT OR REVENUE FLOW.

## 8. Consolidated disposition

| PR | Subject | Current disposition |
|---|---|---|
| #91 | Tenant boundary in generic hash-chain verification | CURRENT-MAIN INVARIANT GAP; port focused fix |
| #92 | Fail-closed IGOR result/provenance checks | CURRENT-MAIN CONTRACT GAP; port focused fix |
| #93 | Public evidence writer boundary | PARTIALLY SUPERSEDED; add size/type limits |
| #94 | Old NINA candidate approval integrity | SUPERSEDED BY CURRENT WORKFLOW APPROVAL |
| #95 | PBKDF2 API-key v2 cutover | SUPERSEDED BY SCRYPT MAINLINE; no blind merge |
| #97 | Exact Stripe session binding | IMPLEMENTED IN MAIN; old PR stale |
| #98 | Old approval serialization flow | SUPERSEDED BY CURRENT WORKFLOW APPROVAL |
| #190 | OIDC Human Gate/customer delivery | HIGH PRIORITY FUNCTIONAL BUG; production bundle not wired |
| #191 | Strict payment/source readiness | STACKED SUPPORTING CHANGE; validate on exact deployment SHA |
| #192 | Docker source identity | STACKED SUPPORTING CHANGE; current deploy SHA mismatch remains |
| #193 | Static revenue-preview headers | STATIC PREVIEW ONLY; SSO verified |
| #194 | Staging console/BFF | DEPLOYED TO SSO-PROTECTED VERCEL STAGING; BFF still relies on external SSO |
| #195 | One-time staging API-key bootstrap | ENDPOINT SUCCESS OBSERVED; deployment is behind current branch head |
| #197 | Certificate Apocalypse | FAIL / NOT RUNNABLE; concrete topology/SAN/assertion defects |
| #198 | Ed25519 Merkle checkpoints | PROTOTYPE / PARTIAL; no production integration |

## 9. Boundaries and next actions

- The 77-row PR CSV remains an initial inventory. This document deep-reviews only the listed priority PRs; the remaining open PR diffs are not reviewed.
- No PR was merged, closed, approved, or changed by this review.
- No branch, main-branch file, production deployment, secret value, database row, GitHub setting or account setting was changed.
- No Vercel or Railway secret value was decrypted.
- The second reviewer login remains of unverified independent/legal relationship to the connected account.
- Next technical priorities: correct #190's locked OIDC revalidation and add positive OIDC tests; fix #197's network placement, container count, SAN and evidence-completeness gates; port #91/#92 fixes onto current main with regression tests; reconcile Railway deployment SHA with configured source SHA and prove readiness stability.
- Preserve the new staging PostgreSQL-aware transaction implementation. Do not reintroduce the old SQLite-only approval guard when rebasing.
- Keep main protection/reviewer controls and production signing/IdP integrations as separate governance/deployment gates.

**Audit state: PARTIAL / HIGH-RISK FINDINGS ISSUED / REMEDIATION NOT COMPLETE.**
