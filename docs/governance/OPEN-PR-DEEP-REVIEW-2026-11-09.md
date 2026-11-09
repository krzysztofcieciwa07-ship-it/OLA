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


## 10. PR #189 — core payment, execution worker, report and PostgreSQL integration review

**PR:** #189  
**Branch:** \`integration/ola-first-five-closure-20261106\`  
**Head:** \`8e56b33df9a3e2806f3709fca90b07e4e595d28f\`  
**Current main:** \`fe32bf8c9710c4c04308ad17f1876fa4f80c01a2\`  
**Diff against current main:** 122 commits ahead, 2 behind; 59 files, +7,148 / -557. The PR was created against an older integration base. This is not a safe direct-merge candidate.

### CI and review evidence

- 41 check-run entries: **38 success, 1 cancelled, 2 skipped** (\`igor-independent\`, \`scorecard\`). A skipped check is not a pass.
- The dedicated real PostgreSQL workflow \`OLA paid-order PostgreSQL contract\` completed successfully on the PR head. Its test log says **8 passed in 0.83s**.
- The PostgreSQL integration suite creates an isolated real PostgreSQL schema and runtime role, runs 32 concurrent appends across 8 workers for one tenant, verifies sequential hashes, checks update/delete rejection, and verifies that startup rejects a runtime role with excessive evidence-table privileges.
- The PostgreSQL workflow only runs \`tests/test_database_postgres_support.py\` and \`tests/test_postgres_integration.py\`. It does **not** run the full paid-order path (Stripe webhook → locked approval → outbox → worker → report review/delivery) against PostgreSQL.
- 16 review submissions were returned; every approval was from the same distinct login \`krzys167-crypto\`. This does not establish independent review. The legal/administrative relationship between that login and the connected account remains unverified.

### Positive implementation controls confirmed

- Stripe webhook verifies the signature and retrieves the authoritative Checkout Session instead of trusting event payload fields. It rejects LIVE mode, requires an exact stored session/order/tenant/request binding, and conditionally claims the payment transition.
- Order approval writes approval evidence, state transition and exactly one outbox row inside the same database write transaction.
- PostgreSQL writes use a tenant-keyed transaction advisory lock; order/control and outbox rows use row-level locks. SQLite uses \`BEGIN IMMEDIATE\`.
- Worker uses a durable outbox, one attempt, source/evidence checks, exact approval binding, and fail-closed \`INTERRUPTED\` handling rather than automatic replay after an ambiguous crash.
- Report review checks the report digest, requester/approver/reviewer separation, and an explicit \`report_reviewer\` API-key role. Delivery is a separate authenticated operation; execution alone leaves \`customer_delivery=NOT_DELIVERED\`.
- The paid-order docs explicitly scope this flow to Stripe test mode and state that it is not production authorization or a real-L​​LM guarantee.

### Confirmed authorization gap: legacy API-key approval has no approver role check

**Files:** \`app/main.py\` blob \`1868b5109c2ecdc95440d2394f88d4fdef828bb2\`; \`app/order_approval.py\` blob \`207920c92cea571b618a397fac05fcd58d65d69c\`; \`app/models.py\` blob \`c0b0721cd5cd83861f7b3cfe0dd0cf4badaf618b\`; test \`tests/test_paid_order_approval.py\` blob \`d9f49c6afd3505109c44b29643a9e06ee688c25c\`.

The legacy \`/checkout-orders/{order_id}/approve\` route resolves a bearer token to only \`(tenant_id, api_key_id)\`. The approval validator checks that the approver key ID differs from the requester key ID, but does not fetch/check an \`execution_approver\` role or an authenticated human identity. The \`ApiKey\` model defaults to \`role="tenant"\`. The positive approval test creates the approver key without specifying a role (therefore the default \`tenant\` role) and successfully receives \`APPROVED_FOR_EXECUTION\`.

This is **key separation**, not verified human separation or SoD. A second ordinary tenant API key is enough for the legacy path. By contrast, the report reviewer path explicitly requires \`report_reviewer\`. The higher-assurance OIDC path in PR #190 adds HR-backed person references and roles, but that PR has the separately confirmed locked-revalidation bug in Section 3.

**Disposition:** HIGH priority before any high-trust Human Gate claim. Either disable legacy API-key approval for the customer path, or require a narrowly provisioned \`execution_approver\` role and bind it to an independently authenticated accountable human. Add negative tests for tenant-role keys and positive tests for the approved role/OIDC identity. Do not treat distinct API-key IDs as proof of distinct humans.

### Confirmed deployment gap: no Railway execution worker is configured

The connected Railway staging environment was re-read:

- It contains exactly one service: \`ola-fastapi-api\`, configured to run the API.
- There is no second worker service and no Railway cron service/schedule.
- The service starts the FastAPI app; the inspected API startup does not launch \`scripts/run_paid_order_worker.py\` as a background process.
- The repository's Docker Compose staging setup does define a separate \`ola-paid-order-worker\` container, but this is local/CI Compose configuration, not the Railway environment.
- The API's HTTP worker adapter \`POST /internal/checkout-execution/{job_id}/run\` calls \`verify_worker_token()\`, which requires \`OLA_EXECUTION_WORKER_TOKEN\`. The connected Railway variable-name inventory does not contain that variable. Values were not read or decrypted.
- The CLI worker can be run manually with database access, but there is no observed Railway process or schedule that starts it.

**Effect:** approval can enqueue a job, but this Railway environment has no configured automatic dispatcher. Unless an external/manual worker is operated, jobs can remain \`QUEUED\`; the HTTP adapter also fails closed without its required token. This is a **fulfilment blocker**, not proof that a worker has never been run manually elsewhere.

**Disposition:** BLOCKED for autonomous paid fulfillment. Configure a separate least-privileged worker service or a controlled external scheduler, provision its required secrets through the deployment secret manager, and verify a real staging order from QUEUED through worker completion. Keep API and worker roles separated; do not expose database migration credentials to the worker.

### Paid-order path is deterministic unless a real LLM is explicitly configured and required

**Files:** \`app/paid_order_execution.py\` blob from PR #189; \`app/nina_execution.py\` blob \`11f7f5e36b2a8cfe135e2e4f0507e10ecc0a45d1\`; \`app/agent_runtime.py\` blob \`0cc9d2af234fcbdde35c251329560900104d121a\`; \`app/nina.py\` blob \`c0bf1e4e6e5e9a5949415ff8daf7a053a15ff0ce\`; \`docs/paid-order-human-gate.md\` blob \`ace72327c7149dc23ceeb8ac526445a9ffe85822\`.

The paid worker invokes the fixed \`safe_expression\` capability. It does not request the \`llm_agent\` capability, which is the capability that explicitly blocks when a real LLM invocation and response ID are missing. \`agent_runtime._invoke_llm()\` defaults to provider \`openai\` and mode \`deterministic\`; when no key is available and mode is not \`required\`, it falls back to \`local_deterministic_model\`.

The connected Railway variable-name inventory for the staging API contains no \`OPENAI_API_KEY\`, \`OLA_LLM_PROVIDER\`, \`OLA_LLM_MODE\`, \`OLLAMA_MODEL\` or Ollama base URL variable. The test named \`test_paid_order_worker_executes_real_nina_and_igor_runtime\` deliberately sets deterministic mode, removes \`OPENAI_API_KEY\`, and asserts \`invocation_type=local_deterministic_model\` and \`real_llm_invoked=false\` while the job still reaches \`EXECUTED_REVIEW_REQUIRED\`.

The documentation does explicitly disclose this limitation: the fixed paid-order path proves a controlled NINA/IGOR runtime, **not** an external/real LLM call. That disclosure is good and must be preserved.

**Disposition:** SCOPE / OFFER GATE. Do not sell or describe this particular paid-order execution as an audit of a real third-party LLM runtime. If the commercial offer requires a real model call, make the provider/model invocation mandatory, require the \`llm_agent\` capability (or equivalent policy), fail closed without it, and include the returned provider/model/response IDs in the signed customer evidence. Otherwise describe the deliverable as a deterministic controlled execution audit.

### Railway build identity: correction and remaining discrepancy

The Railway service config reports builder \`RAILPACK\`, but the deployment build logs explicitly show **\`[internal] load build definition from Dockerfile\`** and execute the Dockerfile steps. In the same deployment's build log, step 4 writes \`/app/ola-build-info.json\` with source commit \`393cc56dcd8c1a749cf11d4306d1e247144139cb\`. The deployment logs then record \`OLA_POSTGRES_SCHEMA=VERIFIED\` and \`GET /readyz 200 OK\`.

Therefore the earlier hypothesis that Railpack ignored the Dockerfile/build-info step is **not supported** and is withdrawn.

One unresolved provenance discrepancy remains: the service source configuration and embedded build-info step both name \`393cc56dcd8c1a749cf11d4306d1e247144139cb\`, while the separate deployment metadata read returned \`030f7f1a4e18ba45da2cc9edbe530ffed92ee56\`. These are distinct commit SHAs. The build logs support the former; the deployment metadata supports the latter. Do not select one silently. Resolve this against a deployment attestation/image digest or a fresh read-only runtime build-info response before claiming which source SHA is serving.

The latest Railway deployment is **SLEEPING** (the service has \`sleepApplication=true\`); it did pass /readyz during its deployment at 02:16 UTC on 2026-11-09 and was stopped at 02:29 UTC. This is intentional sleep configuration, not a current live availability proof. No stability window or customer fulfillment was observed.

### Required follow-up before PR #189 or the paid-order path can be accepted

1. Rebase/reconcile the 122-commit integration against current main; review all conflicting/current-main changes. Do not merge the historical branch as-is.
2. Fix the legacy approval role gap or disable that route for high-trust use; finish PR #190's positive OIDC approval flow, including the locked validation parameters.
3. Deploy and observe the worker separately; show one exact staging order with one outbox job, one execution attempt, verified report review and protected delivery.
4. Run end-to-end paid-order tests against real PostgreSQL, including concurrent duplicate webhook delivery, concurrent approvals, outbox claim races, report review, delivery and interrupted-worker recovery. The current 8-test PostgreSQL contract does not cover these paths.
5. Align commercial wording with the deterministic paid-order path, or make real LLM execution mandatory with provider-bound evidence.
6. Reconcile the conflicting Railway deployment SHA evidence and verify an exact-SHA readiness/runtime window.

No feature branch, PR status, production/staging configuration, deployment, credential, or secret was changed as part of this review.


## 11. PR #198 — signer trust, timestamps and operational boundaries

The detailed implementation and tests were inspected after the initial prototype assessment.

### Positive controls confirmed in source

- The module rejects mixed-tenant record sequences and requires the complete chain from sequence 0 / GENESIS.
- Merkle leaves use domain separation (\`0x00\`) and internal nodes use \`0x01\`; odd-width levels use a documented duplicate-last rule.
- The manifest binds tenant, sequence range, chain tip, record count, algorithm/specification, signer key ID, public-key fingerprint and creation time.
- The manifest signature is Ed25519 over canonical JSON. Signature validity is evaluated separately from signer trust; a signer is only trusted when its public-key SHA-256 matches a separately supplied pinned fingerprint.
- Proof validation checks manifest binding, tenant, tree size, leaf index/sequence, exact proof depth and sibling ordering.
- Tests include mixed-tenant input, cross-tenant proof replay, altered payload/hash, missing sibling, wrong index, odd/even tree sizes, manifest tampering and explicit trusted-fingerprint pinning.
- The workflow is path-scoped and pins checkout/setup-python actions to immutable commits.

### Important trust-boundary requirement

\`verify_checkpoint_signature()\` and \`verify_inclusion_proof()\` default to cryptographic signature validity without requiring a trusted signer. This is intentional: the implementation distinguishes a mathematically valid self-signed checkpoint from an authenticated checkpoint. The docs explicitly instruct production consumers to pass an independently pinned signer fingerprint and \`require_trusted_signer=True\`.

There is no production API/caller in this PR, so this is not currently an exposed endpoint bypass. However, **any future acceptance or customer-delivery path must fail closed unless trusted signer verification is mandatory**. A valid signature from a key supplied inside the same envelope is not proof of OLA/customer identity.

### Forensic and operational gaps are documented, not implemented

- No KMS/HSM-backed signer, authorization policy, key rotation/revocation registry or independent signer enrollment.
- No trusted timestamp authority or external time anchoring. \`created_at\` is part of the signed manifest, but absent TSA anchoring it proves what the signer asserted, not an independently trusted wall-clock time.
- No durable checkpoint store, automatic scheduler, API endpoint, retention policy, external checkpoint chaining or streaming/segmented checkpoint design.
- The current full-chain checkpoint is O(n) in memory and hashing; large chains need a new design rather than silently truncating.
- The loader accepts a \`tenant_id\` parameter and explicitly delegates authorization to its caller. Future endpoints must derive the tenant from authenticated server context, never from a request-supplied tenant selector.
- A Merkle root is an integrity commitment, not encryption, anonymization, proof of truth, or zero-knowledge proof.

**Disposition:** PROTOTYPE / PARTIAL is accurate. The algorithmic checks are materially stronger than the generic current-main verifier, but it is not yet a production evidence-attestation service. Do not make customer/legal forensic claims without trusted key custody, enforced signer pinning, independent timestamping and durable checkpoint anchoring.

## 12. Railway bootstrap-secret reconciliation

The Railway staging service's variable-name inventory currently includes \`OLA_STAGING_BOOTSTRAP_SECRET\`; the values are redacted and the variable is not in the sealed-name list. Therefore the current integration cannot establish whether the value is non-empty or still valid. Historical HTTP logs show one \`POST /_internal/staging/bootstrap-bff-key\` response of HTTP 201 and later HTTP 409 responses.

The route itself requires:
- \`RAILWAY_ENVIRONMENT_NAME=staging\`;
- a bootstrap secret of at least 48 characters;
- constant-time comparison with \`X-Staging-Bootstrap-Token\`;
- absence of the deterministic BFF tenant/service key record before inserting the tenant and API key.

The HTTP 409 on replay is consistent with the database one-time guard. It does **not** prove the bootstrap secret was rotated or removed. The source comment says the token is removed after provisioning, but the route does not erase its own environment variable; that must be performed by deployment configuration after successful bootstrap.

The separate Vercel Preview bootstrap trigger/metadata previously observed as disabled is a different configuration surface. Do not infer that this also removed the Railway variable.

**Disposition:** Historical one-time issuance is observed; current token state is UNKNOWN. Confirm removal/rotation of \`OLA_STAGING_BOOTSTRAP_SECRET\` in Railway through the owner-controlled deployment settings, without displaying its value. Retain only the BFF service key as a sensitive Preview secret. No variable value was read or changed by this audit.


## 13. Audit execution incident — accidental main ref update and clean revert

At 2026-11-09 08:14:00 UTC, one GitHub file-update operation intended for the governance branch created commit \`3034b57ae579bb99a7a6d25f30ac2e2005348da6\` with parent \`fe32bf8c9710c4c04308ad17f1876fa4f80c01a2\`. The connected update wrapper did not preserve the requested branch parameter for that write. The commit added only \`docs/governance/OPEN-PR-DEEP-REVIEW-2026-11-09.md\` and advanced the public \`main\` ref. This was an unintended repository mutation and a process/tooling failure.

Detection: a compare of PR #199's head against \`main\` resolved \`main\` to \`3034b57...\`, and a direct branch lookup confirmed the ref had moved. The commit's file list showed exactly one added governance document; no application code, configuration, secret, deployment or runtime was modified.

Correction: at 2026-11-09 08:19:50 UTC, commit \`b93f25e3df9f90baf1f25259a26df951919b9e7a\` was created as a normal child of \`3034b57...\`, deleting only the accidentally added file. The \`main\` ref was advanced using a fast-forward update with expected head \`3034b57...\`; no force-push or history rewrite was used.

Post-correction verification:
- \`main\` now points to \`b93f25e...\`.
- The revert commit's tree SHA is exactly \`2cbfd61545ddcbb4d224ee5c96d12135dabfb215\`, the same tree SHA as original baseline \`fe32bf8...\`.
- GitHub compare \`fe32bf8... \u0000 b93f25e...\` reports 2 commits ahead, 0 behind and **no file differences**.
- The deep-review document returns NOT_FOUND from \`main\` and is present on the governance branch at blob \`e3bcddb68ea829f215962923a0e40e6f1eca1ed3\`.
- PR #199 is again reported \`mergeable=true / mergeable_state=clean\` at the last poll, and remains Draft/open/unmerged.

The file was briefly available from the public main branch between the two commits. It contained repository findings but no secret values or customer records. This transient public exposure is recorded rather than suppressed.

### Root cause and recurrence prevention

- The file-content wrapper's \`branch\` parameter was not trusted as sufficient evidence that the target ref was correct.
- Future governance writes must use a two-phase method: create blob/tree/commit with the exact currently observed branch-head SHA as parent, then move the ref using \`expected_sha\` and \`force=false\`.
- After every write, fetch the intended branch head and the default branch separately; assert the commit parent and confirm no unintended change to main before reporting success.
- A task is not closed until branch/ref state and the changed-file list have been independently re-read.

**Impact status:** corrected; tree content on main is restored to the original baseline. History retains the add/revert pair. **Process status:** failure recorded; recurrence control adopted for this audit session. This correction does not replace a broader repository-write safety test.


## 14. Re-audit checkpoint — 2026-11-09 09:23 UTC

This recheck supersedes point-in-time provider and ref statuses where noted.

### PR #190 — OIDC locked revalidation and worker binding

The route obtains an OIDC Human Identity actor and passes `approver_principal_id` plus `approver_person_ref` to `approve_paid_order()`. In `app/order_approval.py`, preflight passes both fields to `_validate_paid_order()`, but the second call under the tenant write transaction passes only `approver_id` and `tip_hash`. Since OIDC mode intentionally has no API-key approver ID, the locked call takes the legacy branch and fails with HTTP 400 before commit. This is the exact failing branch, not speculation.

Even after fixing that call, `app/paid_order_execution.py` currently validates the API-key `approver_id` but does not re-bind `approver_principal_id` and `approver_person_ref` to the persisted Human Gate/control data. The worker needs a matching OIDC evidence validation and regression test.

Current tests contain API-key approval happy paths and OIDC_REQUIRED API-key denial tests. They do not demonstrate a successful OIDC approval and dispatch. Report review code has a separate OIDC path that checks active principal, active `report_reviewer` membership and person-reference separation, but a full customer-delivery path for OIDC_REQUIRED is still not implemented; legacy JSON report retrieval returns 409 until a signed bundle exists.

### PR #189 — human accountability and runtime truth

- Current-main compare now shows 122 commits ahead and **4 behind**. Its base SHA is historical; do not merge directly.
- The API-key approval test succeeds with an approver key using the model's default `tenant` role. It proves different key IDs, not independently accountable people or an `execution_approver` role.
- The full paid-order test asserts `local_deterministic_model` and `real_llm_invoked=false`, while the job reaches `EXECUTED_REVIEW_REQUIRED`. The worker does not include `real_llm_invoked` in its independent-check predicate. This is acceptable only when the paid offer is explicitly scoped to deterministic execution; it is not proof of external LLM execution.
- The durable one-attempt worker and fail-closed stale-job reconciliation are positive controls. They do not substitute for deploying a worker consumer.

### Railway staging refresh

At this poll the staging project contains one API service, no worker or cron service, and no configured `OLA_EXECUTION_WORKER_TOKEN`. The configured source SHA is `393cc56dcd8c1a749cf11d4306d1e247144139cb`; the latest SUCCESS deployment metadata identifies `030f7f1a4e18ba45da2cc9edbe530ffed92ee56` (three commits behind). The latest deploy has `sleepApplication=true`; readiness logs include both a transient HTTP 499/connection-refused startup window and subsequent 200 responses. No continuous availability window was measured. `OLA_STAGING_BOOTSTRAP_SECRET` remains in the variable-name inventory; its value is redacted and current validity is UNKNOWN.

### PR #197 SAN and hidden assertion blockers

The generated leaf SAN omits `tls-target` (it contains localhost, tls-under-test and 127.0.0.1), so strict hostname validation remains broken after network resolution is repaired. Three Compose containers are expected but the assertion checks for two. The public `private_assertion_policy=true` flag has no private assertion pack behind it. Manifest missing-file reporting is not itself a hard failure gate.

### Current PR #199 state

Head `c42a32237500a48b27828e0218e42b2642c883d3`, OPEN / DRAFT / UNMERGED. Thirty check runs returned 28 success and 2 skipped (`igor-independent`, `scorecard`); there are no submitted reviews. This remains a documentation-only proposal awaiting independent review, not an accepted baseline.

**Status:** selective re-audit advanced; remediation remains incomplete. No application source, production deployment, secret, database row or repository setting was changed.
