# GitHub Portfolio and High-Trust Readiness Audit

**Audit date:** 2026-11-09  
**Status:** FINDINGS ISSUED / REMEDIATION NOT COMPLETE  
**Scope:** the 10 repositories returned by the connected GitHub account and 32 public repositories discovered under the second public login. This is not a review of inaccessible private repositories, external provider settings, or every source line in all 42 repositories.

## 1. Executive result

The portfolio is **not ready to be presented as a company portfolio of high-trust systems**.

The audit found:
- two accounts with 42 visible repositories and 355 branch refs across the repository inventories;
- 33 GitHub forks and 9 repositories marked as non-forks; fork status is a GitHub relationship, not proof of legal ownership;
- a wide-open GitHub App installation on the connected account;
- insufficient merge protection on the primary OLA repository;
- two failed and one skipped check context on the reviewed OLA main SHA;
- material OAuth, token-handling and action-confirmation weaknesses in Quantum AI Chatbot;
- a mismatch between the Vantage v0.3 hosted-range assurance claim and the test workflow that currently builds its supposed private pack from public assertions;
- host-level blast-radius risks in the Vantage v0.3 installer;
- a specification-only Evidence Gateway repository with an unrelated homepage URL;
- tracked `.env` files in the older Quantum repository and the GoalFloow fork.

These are code/configuration findings. No evidence was found in this audit that any weakness was exploited.

## 2. Account, access and repository inventory

### Connected account: `krzysztofcieciwa07-ship-it`

- 10 repositories returned by the authenticated GitHub connector.
- Repository administration permissions are available on these 10 repositories.
- No organization memberships were returned.
- The GitHub App installation ID `161065414` uses `repository_selection: all`. The app can therefore access all repositories in this account, rather than only the repositories required for the current task.
- MFA/passkey status was not exposed by the integration: **UNKNOWN**.
- No second independently accountable reviewer was verified.

### Second public login: `krzys167-crypto`

- 32 public repositories were discovered and their repository metadata was readable.
- The connected integration has read-only access to these repositories (`pull=true`, `push=false`, `admin=false`).
- The second account's private repositories, account security settings and administrative policies were not visible.
- Whether the two GitHub logins are controlled by the same legal owner or company was not established.

### Fork and ownership interpretation

The GitHub metadata identifies 33 of the 42 repositories as forks and 9 as non-forks. This does not prove ownership of the non-fork repositories and does not transfer ownership of forks.

Important verified relationships:
- `krzys167-crypto/OLA` is a fork of `krzysztofcieciwa07-ship-it/OLA`, not an independent canonical repository. It has divergent commits/history that still require a commit-level reconciliation.
- `krzysztofcieciwa07-ship-it/quantum-ai-chatbot` is a fork of `krzys167-crypto/quantum-ai-chatbot`.
- `krzysztofcieciwa07-ship-it/ola-evidence-gateway` is a fork of `krzys167-crypto/ola-evidence-gateway`.
- `krzys167-crypto/vantage` is a fork of `krzysztofcieciwa07-ship-it/vantage`.
- The connected account's `MetaGPT`, `cli`, `ai`, `uygulamali-kriptografi` and `swarmclaw` repositories are upstream forks, not original OLA products.
- `krzys167-crypto/MetaGPT`, `cli`, `ai`, `swarmclaw`, `google-api-nodejs-client`, `docs`, Homebrew repositories and other upstream mirrors are also not proprietary product deliverables.

Do not list forks as company-owned products without a license/rights review and an accurate description of original work.

## 3. Repository-level classification

### Product and prototype repositories

| Repository | Observed state | Audit classification |
|---|---|---|
| `krzysztofcieciwa07-ship-it/OLA` | Primary non-fork OLA repository; Python/FastAPI runtime, tests and 25 workflow files. Public; Unlicense; description, homepage and topics empty. | **CORE, governance FAIL / remediation required** |
| `krzys167-crypto/OLA` | Fork of primary OLA; substantially divergent history and additional code/docs. Read-only to this integration. | **DIVERGENT FORK, reconcile unique commits** |
| `krzysztofcieciwa07-ship-it/vantage` | Small Python AFE/risk-gate prototype; 3 workflows; no license, security policy or CODEOWNERS observed. | **EXPERIMENTAL PROTOTYPE, not production verified** |
| `krzys167-crypto/Vantage-v0.3` | Separate non-fork repo; 180 files; DSL, grader, hosted-range and four incident scenarios. Default branch is `claude/powershell-install-script-h86qlw`; no license/security policy/CODEOWNERS observed. Read-only to this integration. | **PRODUCT CANDIDATE, critical hardening required; ownership/admin control not verified** |
| `krzysztofcieciwa07-ship-it/Vantage-v0.3` | Private repository is empty (size 0; no main branch found). | **EMPTY PLACEHOLDER, not the implementation source** |
| `krzys167-crypto/vantage` | Fork of the connected account's Vantage prototype. | **FORK, not a separate product** |
| `krzys167-crypto/quantum-ai-chatbot` | Original repository; tracks `.env`; no GitHub workflow directory observed. | **LEGACY SOURCE, security remediation required** |
| `krzysztofcieciwa07-ship-it/quantum-ai-chatbot` | Fork of the older Quantum repository; one security workflow; `.env.example` only in the checked tree. | **EXPERIMENTAL APP, HIGH-RISK OAuth and action authorization findings** |
| `krzys167-crypto/ola-evidence-gateway` | Original repository, README only in checked root. Metadata has no description and points homepage at an unrelated weather URL. | **SPECIFICATION, not a running gateway** |
| `krzysztofcieciwa07-ship-it/ola-evidence-gateway` | Fork with three tracked files (README plus editor/devcontainer configuration), no gateway implementation or tests. Homepage is `https://moja-pogoda.vercel.app`. | **SPECIFICATION FORK / ARCHIVE CANDIDATE** |
| `krzys167-crypto/Ola-ai-plugins` | README-level concept; no implementation. | **SPECIFICATION** |
| `krzys167-crypto/goalfloow` | Upstream fork; tracked `.env`; .gitignore does not ignore it. | **UNRELATED FORK, secret hygiene FAIL** |
| `krzys167-crypto/TIMEATLAS` | Tiny repository; root listing contains .github and .gitignore only. | **UNKNOWN / needs owner decision** |
| `krzys167-crypto/vigilant-fiesta` | Empty repository according to GitHub size metadata, with a README in the root listing. | **UNKNOWN / low-value placeholder** |
| `krzys167-crypto/ola.dios.audit-gmail.com` | Fork of `oladiosaudit-tech/ola.dios.audit-gmail.com`; README is only 26 bytes. | **FORK, purpose and rights unverified** |

The remaining repositories are upstream forks or reference projects. They should not appear in the proprietary OLA product showcase: `MetaGPT`, `cli`, `ai`, `uygulamali-kriptografi`, `swarmclaw`, `agent-os`, `awesome-python`, `MoneyPrinterTurbo`, `CLI-Anything`, `dotfiles`, `brew`, `arrow`, `community`, `django-ai-plugins`, `congress-tracker`, `avalanche-react`, `RobynAwesome`, `google-api-nodejs-client`, `docs`, `house-documents`, `homebrew-cask` and `homebrew-core`. Preserve upstream attribution and licenses.

## 4. OLA primary repository: governance and CI

### Confirmed controls

- Active repository ruleset ID `25853037`, name `SECURITY.md`.
- Effective rules visible through the current connector: branch deletion and non-fast-forward update prevention only.
- No required PR approval count and no required status checks are defined in that ruleset.
- Main branch API returned `protected=false`; classic branch protection could not be fully verified through the available connection.
- `.github/CODEOWNERS` names only `@krzysztofcieciwa07-ship-it`. This is not independent review.
- 167 branches and 77 open PRs were present in the audited snapshot: 65 Draft and 12 ready for review.
- Five duplicate-HEAD branch groups were found. One group is tied to open PR #189 and must be retained until that PR is resolved. Identical HEADs alone are not sufficient evidence for deletion.
- The open-PR triage CSV in this branch records all 77 PRs as `UNREVIEWED`. It is a triage inventory, not an assessment of every PR diff.

### Main exact-SHA checks

For `main` SHA `fe32bf8c9710c4c04308ad17f1876fa4f80c01a2`, the latest result per context was:
- 30 success
- 2 failure
- 1 skipped

Failed contexts:
- `classify`
- `real_ollama_flow / nina-igor-ollama-full-flow`

Skipped:
- `igor-independent`

A skipped verifier is not a pass. The main SHA is not green.

**Root-cause clarification from the exact job logs:** the real Ollama full-flow job fails in `Set up Ollama` before the OLA application or agent flow starts: the installer download of `ollama-linux-amd64.tgz` returns HTTP 504, followed by a truncated gzip/tar error. The `classify` job then records `real_ollama_full_flow_failed` and fails closed because the Ollama job failed. These are two failed contexts but one evidenced upstream infrastructure failure plus its deliberate downstream fail-closed consequence; they are not evidence of two independent application-logic defects. The runtime chain remains **UNVERIFIED** for this SHA.

### Positive supply-chain observations

- The 25 workflows in the connected OLA main tree contain explicit `permissions` blocks.
- Third-party GitHub Actions observed in these workflow files are pinned to full commit SHAs rather than mutable version tags.
- The reviewed OLA workflow files did not contain `pull_request_target` or `secrets: inherit`.
- The root tree scan did not identify tracked `.env`, private-key or credential-named files.

These positives do not replace the unavailable Code Scanning, Secret Scanning and Dependabot alert views. Those alert endpoints were not accessible through the current GitHub integration; alert status is **UNKNOWN**, not clean.

### Stale ruleset activation script

`scripts/apply_main_ruleset.py` must not be run as-is:
- its check list is tied to a previously observed, older main SHA;
- the current main check inventory differs;
- its policy sets `require_code_owner_review: false`;
- it must be regenerated from verified current check contexts and an approved independent-review policy.

## 5. Quantum AI Chatbot: HIGH-RISK findings

Reviewed paths include:
- `api/connectors/google-start.js`
- `api/connectors/google-callback.js`
- `api/connectors/microsoft-start.js`
- `api/connectors/microsoft-callback.js`
- `api/lib/google.js`
- `api/lib/microsoft.js`
- `api/lib/supabaseAdmin.js`
- `api/lib/claudeTools.js`
- `api/lib/executionPolicy.js`
- `supabase/connectors.sql`
- `.github/workflows/security-gate.yml`

Findings:

1. **OAuth state is not authenticated.** The start endpoints encode `{userId, provider, t}` as Base64. The callbacks decode it and trust the supplied user ID/provider. There is no HMAC/signature, server-side one-time state record, nonce/session binding or timestamp validation in the reviewed flow. This creates an account-linking/CSRF risk. Exploitability has not been demonstrated in a live deployment.
2. **OAuth tokens have no visible application-layer encryption.** The schema stores `access_token` and `refresh_token` in ordinary text fields. Server routes use the Supabase service-role client to read/write them. Storage encryption at the provider level is separate and was not assessed.
3. **Human confirmation is not independent.** Write-capable tools accept `user_confirmed: true` from the model-generated tool input. The policy checks this boolean but does not bind it to a separate server-side user confirmation transaction. It therefore does not constitute a trustworthy Human Gate.
4. **Gmail scopes exceed the stated read-only behavior.** The code requests `gmail.send`, `gmail.compose` and `gmail.modify` in addition to `gmail.readonly`. The README's read-only wording is inaccurate.
5. **Microsoft scopes need minimisation.** The Excel connector includes `Files.Read` and `Sites.Read.All`, which is a broad permission footprint for a narrow workbook search feature.
6. **CI hardening is incomplete.** The one Quantum security workflow uses `actions/checkout@v4` and `actions/setup-node@v4` rather than immutable commit SHAs. It runs npm test/build but no CodeQL, secret scanning or dependency review workflow was observed.
7. **Rate limiting is per process.** The implementation explicitly documents that its in-memory limiter does not coordinate across serverless instances.

Required remediation before customer OAuth use:
- authenticated, one-time, session-bound OAuth state (and PKCE where supported);
- encrypted token storage with key management and rotation;
- reduce provider scopes to the minimum required;
- implement an independent, authenticated confirmation record for every external side effect;
- verify tenant boundaries and connector revocation end-to-end;
- pin workflow actions to SHAs and add secret/dependency/code scanning.

## 5.1 Vantage prototype workflow supply chain

The connected-account `krzysztofcieciwa07-ship-it/vantage` has three workflows. The reviewed workflow action references include:
- `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`;
- `sigstore/cosign-installer@main` in `verify.yml` and `provenance-independent.yml`;
- `sigstore/cosign-installer@v3.7.0` in `cfr18.yml`.

These version tags/branches are mutable references, not immutable full commit SHAs. The workflows define explicit permission blocks, and `provenance-independent.yml` runs on `workflow_run` completion with read-only `actions: read`, `contents: read` permissions and verifies the artifact's Cosign identity, issuer, commit and file digests. The verification design has useful checks, but its action supply chain still needs immutable pinning. The README correctly classifies the code as a prototype; its deterministic E2E and replay are not proof of live LLM availability or production operation.

## 6. Vantage v0.3: HIGH-RISK hosted assurance and host isolation findings

Reviewed paths include:
- `grader/server.py`, `grader/identity.py`, `grader/jwks.py`
- `range/range.sh`, `range/api.py`
- `scenarios/certificate-apocalypse/ci/assertions.sh`, `ci/hidden.sh`
- `.github/workflows/scenarios.yml`
- `deploy/install.sh`
- `docs/grader.md`, `docs/hosted-range.md`

Findings:

1. **Private assertion pack CI is not independent.** In the `hosted-range` workflow, the supposed private pack is built by copying the public scenario `ci/hidden.sh` and appending a comment containing the run ID. Its hash is registered as a private pack. This proves the grader's pack-hash plumbing, not independent secret assertions unavailable to the participant. Documentation and assurance labels must not imply a genuine independent private pack has been tested.
2. **Docker group is a high-privilege boundary.** The installer creates the `vantage` system user in the `docker` group. Access to a rootful Docker socket is effectively host-root equivalent; the service's `NoNewPrivileges=true` does not make Docker socket access harmless.
3. **Kubernetes API exposure is broad by default.** The installer creates k3d with API bound to `0.0.0.0:6443` and opens TCP/6443 in UFW. A scoped trainee kubeconfig is positive, but it does not justify exposing the control-plane endpoint broadly.
4. **Branch governance is inadequate.** The active ruleset has zero required approvals and an empty required status-check list. All 15 listed branch refs returned `protected=false`. No CODEOWNERS or security policy was observed.
5. **Workflow supply chain is weaker than OLA.** `scenarios.yml` uses mutable `@v4` action tags and retrieves k3d's installer script from the repository's moving `main` branch via curl-to-shell.
6. **No license is declared.** Do not infer rights to commercially redistribute or relicense this public repository. Ownership/administrative control of the account was not established by the connected integration.
7. **Local graded mode has documented client-trust limits.** The Vantage documentation itself says local assertions are client-reported and local hidden checks are visible. The true trust boundary must be hosted infrastructure with platform-run assertions, private tests and a participant role that cannot inspect/alter the prober or secrets.

Required remediation before hosted-range trust claims:
- build and test a real private assertion pack from a private source independent of the participant-visible repo;
- verify the pack content and digest with platform-controlled evidence;
- move Docker access out of tenant-facing service identities (rootless or isolated privileged controller/VM);
- restrict the k3d control-plane API to private access, VPN or strict allowlist;
- pin all workflow actions and installer binaries/scripts immutably;
- define license, security policy, CODEOWNERS and real PR/check gates;
- enforce identity provider/JWKS authentication in production configuration, and fail startup if identity is not configured.

## 7. Other hygiene and security findings

- `krzys167-crypto/quantum-ai-chatbot` tracks `.env`; `krzys167-crypto/goalfloow` also tracks `.env` and its .gitignore does not exclude it.
- Previous safe token-payload inspection of these files identified a Supabase `anon` key, not a `service_role` key. No administrative key was confirmed in the reviewed content. This does not excuse tracked environment files; remove them from the index and inspect full Git history with a secret scanner.
- `krzys167-crypto/quantum-ai-chatbot` has no GitHub workflow directory in the inspected default branch.
- The Evidence Gateway repositories are documentation/specification, not running services. The connected copy has only three tracked files and an unrelated weather homepage URL.
- The private connected `Vantage-v0.3` repository is empty; it must not be labelled as the source of the developed Vantage implementation.
- The Vantage prototype README itself accurately says it is a prototype and not production verified. Preserve that wording.

## 8. Controls not verified

The following remain **UNKNOWN** because the required account-level/administrative data or external system access is unavailable:
- MFA/passkey status for the account owner.
- Private vulnerability reporting configuration.
- Code Scanning, Secret Scanning and Dependabot alert state for OLA.
- Classic branch-protection settings where the connector cannot read the endpoint.
- Settings and private repositories on the second account.
- Vercel, Supabase, Google Cloud and Microsoft Entra production configuration, secret values, OAuth app scopes, DB policies in a live project, runtime deployments, backup/restore and incident logs.
- Whether the second GitHub login is legally controlled by the same person/company.
- Legal ownership, license grants and rights to commercialise each non-fork repository.

No live deployment, OAuth abuse, token exposure or secret compromise was demonstrated by this repository audit.

## 9. Priority remediation order

1. **Contain Quantum integration risk:** disable customer access to write-capable OAuth tools until state validation, server-confirmed human approvals and token encryption are implemented.
2. **Contain Vantage host risk:** do not expose the installer-created Kubernetes API to the public internet; remove rootful Docker socket access from tenant-facing identities.
3. **Correct the Vantage assurance claims:** stop calling the CI-derived copy of public assertions a private hidden pack; implement a truly independent private pack.
4. **Protect OLA main:** obtain an independent reviewer, require PR approval and current exact-SHA checks, map CI contexts and remove the stale ruleset activation script from any auto-apply path.
5. **Reduce account blast radius:** narrow GitHub App installation ID `161065414` from all repositories to the minimum required set.
6. **Fix public portfolio identity:** stop presenting upstream forks and README-only specifications as proprietary products; correct/clear the Evidence Gateway homepage.
7. **Clean tracked environment files:** remove tracked `.env` from old Quantum and GoalFloow and run full-history secret scanning; rotate any credential if any real secret is found.
8. **Establish ownership and licensing:** verify account ownership/admin control of Vantage v0.3; add approved license/security policy to the repositories that are actually company assets.

## 10. Audit execution boundary

This report records read-only repository and code inspection. No repositories, branches, files on `main`, credentials, visibility, collaborators or external deployments were deleted or changed as part of the audit. The governance remediation documents remain in Draft PR #199 and are not merged.


## 11. Execution quality, chronology and forensic closure

The repeatable task-level standard is defined in [EXECUTION-QUALITY-AND-FORENSIC-PROTOCOL.md](EXECUTION-QUALITY-AND-FORENSIC-PROTOCOL.md). It requires a task contract, UTC event chronology, exact revision/environment identity, preserved and hashed evidence, verification of actual results, critical self-review, failure-register updates and an honest closure state. The existence of the protocol is not evidence that all tools and repositories enforce it yet.


## 12. Follow-up CI audit: exact PR head and current main

### PR #199 head: `8b914b9960843a96aa6d59686fd5c2b67ac833e0`

The governance branch head was rechecked against the GitHub API on 2026-11-09. At this snapshot:

- PR #199 remains **OPEN / DRAFT / UNMERGED**; `mergeable=true`, `mergeable_state=unstable`.
- The PR contains 8 files and is 24 commits ahead of `main`, 0 behind at the compared refs.
- There are **0 submitted reviews** and no requested reviewers.
- 30 check-run entries were completed: **25 success, 3 failure, 2 skipped**. This is a check-run count, not a statement that every workflow was green.
- Successful checks include CodeQL, Trivy, Gitleaks, zizmor, build-linux, focused tests, E2E, stress, continuity, evidence-graph, provenance mutation and product/revenue gates.
- Skipped contexts: `igor-independent` and `scorecard`. Neither counts as a pass.

The three failed check contexts have this relationship:

1. `NINA IGOR Ollama Full Flow`: `Set up Ollama` fails before building or starting OLA. The Ollama installer downloads `ollama-linux-amd64.tgz` and receives HTTP 504; subsequent gzip/tar commands report a truncated archive. The NINA → IGOR → provenance → replay assertions are **not executed**.
2. `Real LLM Ollama Runtime Gate`: the same installer/download path fails with HTTP 504 before model inventory, OLA build, six-agent runtime or standalone verifier. The live LLM path is **not executed**.
3. `OLA FINAL PRODUCTION GATE`: the gate reads the failed required NINA/IGOR run and fails closed in `Verify required evidence gates`. Release image build, export and attestations are skipped. The workflow does upload a manifest with `final_status=BLOCKED`; that is evidence of a block, not a release artifact or production deployment.

The two Ollama jobs use `curl -fsSL https://ollama.com/install.sh | sh`. In the reviewed workflow source, the installer itself is not pinned to a fixed version or verified against a pre-declared SHA-256 digest, and the download path has no bounded retry/backoff for transient 5xx failures. This produces both supply-chain reproducibility risk and avoidable CI availability fragility. The current 504 is an observed external download failure; it does not establish that Ollama or OLA is generally unavailable.

**Interpretation:** the governance branch has useful positive test/security signals, but its overall exact-SHA CI result is **FAIL / PARTIAL**, not green. The live Ollama runtime is **UNVERIFIED**, not failed by an observed application assertion. The production gate correctly withheld image build/attestation after the required runtime check failed. No production deployment occurred.

### Main remains separate

The main branch still points to `fe32bf8c9710c4c04308ad17f1876fa4f80c01a2`; the API reports `protected=false`. The latest check-run response contains 38 entries (including repeat contexts across runs): 35 success, 2 failure and 1 skipped. The two red contexts are the failed real Ollama full-flow job and its downstream fail-closed `classify` result described in Section 4. This is the current main state observed during this follow-up, not a PR-branch result.

### Required corrective actions (not performed by this audit)

- Replace moving installer execution with a pinned Ollama release artifact or immutable image digest; verify its SHA-256 against a trusted, version-controlled expected value before execution.
- Add bounded retries with exponential backoff and jitter for transient 5xx/network failures; preserve the final response code and download diagnostics.
- Avoid running duplicate Ollama installation paths where one controlled, reusable, version-pinned runtime fixture can safely provide evidence to both test suites.
- Keep the final production gate fail-closed; improve its evidence output so a blocked upstream dependency is distinguished from a product assertion failure.
- Re-run the real-model flow and final gate on a new exact commit. Do not mark runtime verified based solely on a successful installer, model download or deterministic test.

No workflow, deployment, main-branch file, repository setting or secret was modified as part of this follow-up audit.


## 13. Selective deep review of open PRs and live staging

The detailed, row-by-row findings for the high-risk subset are recorded in [OPEN-PR-DEEP-REVIEW-2026-11-09.md](OPEN-PR-DEEP-REVIEW-2026-11-09.md). This is a selective deep review, not a claim that all 77 open PR diffs have been reviewed.

### Material current-main findings

- The generic verify_chain() helper does not require all records in its input to share one tenant ID. Current call sites commonly tenant-filter records, which constrains the normal path, but the generic invariant remains incomplete. PR #91 contains a focused fix and cross-tenant regression test.
- IgorVerifier can match a missing result against expected_result=None through string conversion, and can evaluate provider/model/response IDs across different provenance records. Current NINA flow normally supplies a result string and one provenance record; the generic verifier contract still needs the stricter #92 checks.
- The main evidence write route already blocks privileged type prefixes and caller-supplied reserved V2 metadata, so the primary public privileged-record forgery path is mitigated. Explicit payload-size and public record-type limits remain.
- Stripe success is already bound to the exact Checkout Session in main and covered by a regression test. PR #97 is stale/superseded.
- The old candidate approval paths in #94/#98 are superseded by the current /nina-workflow/{run_id}/approve path, which checks tenant-scoped DAG evidence, requester/approver separation, report digest and rechecks the chain tip under a write transaction.

### PR #190 and #197 blockers

- PR #190's OIDC paid-order approval has a confirmed defect: the OIDC identity is passed to preflight validation but omitted in the second locked revalidation. Valid OIDC_REQUIRED approvals therefore fail closed with HTTP 400 before approval evidence/outbox commit. Existing tests cover legacy approval and API-key denial, not a successful OIDC operator approval.
- PR #197's CI run fails at readiness because the host-side probe cannot resolve Docker-internal service DNS. Compose starts three services while a later assertion expects two; the generated certificate SAN does not include the configured tls-target hostname. Its public DSL flag for private assertions does not implement a hidden private pack, and missing evidence files are recorded but do not independently fail score generation.

### External staging controls rechecked

- The Vercel project used by the #194 staging deployment has SSO protection enabled for all deployments. The exact deployment is a staging deployment built from the #194 head. The BFF key appears as a sensitive Preview-only variable; secret values were not decrypted.
- The Railway staging service has a real public service hostname and a current latest deployment in SLEEPING state. Historical HTTP logs show one successful bootstrap response (201), later replays rejected (409), and /nina-run returning HTTP 200; this does not establish verified runtime output or customer delivery.
- The Railway service configuration identifies source SHA 393cc56dcd8c1a749cf11d4306d1e247144139cb, while the latest deployment metadata identifies 030f7f1a4e18ba45da2cc9edbe530ffed92ee56. GitHub compare shows the deployed SHA is three commits behind the current branch head. The live revision must be reconciled before claiming the latest staging branch is running.
- A previous Railway deployment failed its /readyz healthcheck despite process startup and a PostgreSQL schema verification message. A later deployment was created, and the latest deployment is currently sleeping.

### Corrected inference: PostgreSQL Human Gate

The old main implementation of approve_workflow() rejects non-SQLite databases. The current staging branch, however, contains a later begin_write_transaction() implementation that supports PostgreSQL using a tenant-scoped advisory transaction lock, and its approval module calls that abstraction. Therefore the earlier possibility that the active staging approval route necessarily returns 503 is not confirmed for the deployed staging branch. Preserve this PostgreSQL-aware implementation when rebasing; do not reintroduce the old SQLite-only guard.

### Open-PR disposition

PR #91/#92 require focused fixes ported onto the current main base. PR #93 is partially superseded and needs payload/type hardening. PR #94/#98 and #97 are superseded by current main behavior and should not be merged blindly. PR #95's PBKDF2 branch is superseded by the scrypt mainline and its SQLite reissue script is not appropriate for the current PostgreSQL staging service. PR #190 and #197 have explicit blockers. PR #198 remains a prototype, not a production-integrated checkpoint service.

No feature PR, branch, main-branch file, deployment, secret or repository setting was changed by this selective review. The 77-row CSV remains the initial inventory; only the subset named in the deep-review document has been reviewed at code level.


## 14. PR #189 core payment and execution path — deeper review

PR #189 (`integration/ola-first-five-closure-20261106`, head `8e56b33df9a3e2806f3709fca90b07e4e595d28f`) is a 59-file integration with 122 commits ahead of current main and 2 behind. It must not be merged directly without reconciling its old base with current main.

### Verified positive evidence

- Exact-head CI: 41 check-run entries, 38 success, 1 cancelled, 2 skipped (`igor-independent`, `scorecard`).
- The dedicated real-PostgreSQL workflow completed **8 tests successfully**. It validates concurrent append sequencing, tenant advisory locking, append-only triggers and the limited runtime role.
- The Stripe webhook checks signed sandbox events, retrieves the authoritative Checkout Session, binds the session to the exact order/tenant/request hash and uses conditional state transitions.
- Approval, evidence append and the outbox job are committed in one database transaction. The worker is designed for one attempt and marks ambiguous/stale work interrupted instead of replaying automatically.
- Report review uses a specific `report_reviewer` API-key role and a separate authenticated review/delivery path.

### Remaining high-risk issues

1. **Legacy approval is not a role-bound human gate.** The ordinary `/checkout-orders/{order_id}/approve` path checks that the API key ID differs from the requester but does not require an `execution_approver` role or bind the key to an authenticated human. The `ApiKey` model defaults to `role="tenant"`; the positive approval test uses that default role and succeeds. This proves two-key separation, not independent human SoD. PR #190's OIDC identity path is the intended higher-assurance correction, but the second locked validation currently omits the OIDC identity fields and fails closed.
2. **No Railway worker service is configured.** The Railway staging environment contains one API service and no cron/worker service. The API's worker HTTP adapter requires `OLA_EXECUTION_WORKER_TOKEN`, which is absent from the connected service-variable-name inventory. The repository's local Compose file has a separate worker container, but that is not deployed in Railway. Without a manually operated external worker or a separate configured service, approved jobs can remain in `QUEUED`.
3. **The paid-order worker does not prove a real LLM call.** It requests the fixed `safe_expression` capability, not `llm_agent`. In `agent_runtime.py`, the default mode is `deterministic`; absent a provider key, the runtime falls back to `local_deterministic_model`. The connected Railway variable inventory has no OpenAI key, Ollama endpoint/model, provider or mode override. The paid-order test with “real NINA and IGOR runtime” in its name explicitly sets deterministic mode and asserts `real_llm_invoked=false`. The product documentation correctly says this is a controlled deterministic NINA/IGOR run, not proof of an external LLM call. Do not position this paid path as a real-LLM runtime audit unless the offer is changed to require a provider-bound LLM invocation and its response IDs.
4. **PostgreSQL test coverage is incomplete for the paid workflow.** The current PostgreSQL CI only runs the database-support and PostgreSQL integration test files. It does not cover the full webhook, paid-order approval, execution worker concurrency, report review or delivery flow against PostgreSQL. The 8 passing tests do not close those gaps.

### Railway source and runtime evidence — corrected interpretation

The service config is labelled `RAILPACK`, but the actual deployment build log explicitly loads the repository Dockerfile, executes its stages, and runs the step writing `/app/ola-build-info.json` with source SHA `393cc56dcd8c1a749cf11d4306d1e247144139cb`. The same deployment logs `OLA_POSTGRES_SCHEMA=VERIFIED` and `GET /readyz 200 OK` at 02:16 UTC on 2026-11-09. The earlier hypothesis that Railpack ignored the Dockerfile/build-info step is therefore withdrawn.

There is still a conflicting source record: Railway service configuration and the build-info step both report SHA `393cc56dcd8c1a749cf11d4306d1e247144139cb`, while the deployment metadata read separately reported `030f7f1a4e18ba45da2cc9edbe530ffed92ee56`. Treat this as an unresolved provenance discrepancy; do not claim either source solely from one record. The latest deployment is currently `SLEEPING` because `sleepApplication=true`, after its readiness check succeeded. No sustained availability window or live paid-order fulfillment was observed.

### Disposition

PR #189 is **NOT READY FOR MERGE**. It has positive PostgreSQL and payment-control foundations, but needs a current-main reconciliation, a role-bound Human Gate, a deployed worker, real-PostgreSQL paid-flow tests, and a precise commercial boundary for deterministic versus real-LLM execution. The exact source/deployment SHA discrepancy must be reconciled before production provenance claims.


## 15. Additional review: Merkle trust defaults and Railway bootstrap credential state

### PR #198 — cryptographic validity is not signer identity

The v0.1 Merkle implementation and tests were re-read. It rejects mixed tenants and invalid chains, domain-separates leaf/node hashes, signs a canonical manifest with Ed25519 and exposes a separate trusted-fingerprint decision. The implementation intentionally defaults to reporting \`signature_valid\` separately from \`signer_trusted\`; proof verification requires the caller to opt into \`require_trusted_signer=True\` with an independently pinned fingerprint.

There is no public API consumer in this PR, so no current route bypass was confirmed. The production acceptance boundary must make trusted signer verification mandatory. Otherwise an envelope that supplies its own public key can be mathematically valid without proving OLA/customer identity. The module also lacks production KMS/HSM custody, key enrollment/revocation, TSA timestamping, durable checkpoint persistence/scheduling and externally anchored checkpoint chaining; the docs disclose these limits. The signed \`created_at\` is a signer assertion, not independent timestamp proof.

### Railway bootstrap variable — corrected scope

The Railway staging variable-name inventory contains \`OLA_STAGING_BOOTSTRAP_SECRET\`, but OAuth integration withholds its value and it is not listed as sealed. Current non-empty/valid status is therefore **UNKNOWN**. Historical logs prove the bootstrap endpoint returned HTTP 201 once and HTTP 409 on subsequent calls. The route's database existence guard prevents a second issuance while the bootstrap tenant exists; the HTTP 409 does not prove the secret was rotated or deleted.

The Vercel Preview bootstrap metadata previously observed as disabled applies to the Vercel deployment surface, not necessarily the Railway service variable. The route's own code does not remove the environment variable. Owner-controlled post-bootstrap rotation/removal in Railway remains an outstanding hygiene action; no secret value was read or modified.


## 16. Forensic incident record — unintended main update and revert

A governance-document update intended for \`governance/cyfun-2025-portfolio-hardening-20261109\` created commit \`3034b57ae579bb99a7a6d25f30ac2e2005348da6\` at 08:14:00 UTC with parent equal to the then-main SHA \`fe32bf8c9710c4c04308ad17f1876fa4f80c01a2\`. The GitHub file-update wrapper did not preserve the requested target branch. This advanced public \`main\` and added exactly one file: \`docs/governance/OPEN-PR-DEEP-REVIEW-2026-11-09.md\`. No application source, secret, customer record, deployment, environment variable or runtime configuration was changed by that commit.

The ref drift was detected by comparing PR #199 against \`main\` and then independently reading \`branches/main\` and commit 3034. A corrective fast-forward revert was created at 08:19:50 UTC: \`b93f25e3df9f90baf1f25259a26df951919b9e7a\`, parent \`3034b57...\`. It removes only the accidentally added document. The ref update used \`expected_sha=3034b57...\` and \`force=false\`; no history rewrite occurred.

Post-correction evidence:
- Current main ref: \`b93f25e...\`.
- Revert tree SHA: \`2cbfd61545ddcbb4d224ee5c96d12135dabfb215\`.
- Original baseline \`fe32bf8...\` has the same tree SHA.
- GitHub compare baseline → revert: 2 commits ahead, 0 behind, no file changes.
- The document returns NOT_FOUND on main and is verified on the governance branch.
- PR #199 is back to \`mergeable=true / clean\` at the last poll; it remains Draft/open/unmerged.

The document was briefly reachable from public main for approximately 5 minutes 50 seconds. It contained audit findings already visible in the public governance branch and no secret values or customer records. The incident is retained in the event chronology; no claim of zero exposure is made.

**Root cause:** reliance on the file-update wrapper's requested branch field without asserting the actual commit parent/ref after the write.

**Preventive control adopted for subsequent writes:** use Git objects + exact parent SHA + fast-forward \`update_ref(expected_sha, force=false)\`; then independently re-read both target branch and main. Every mutation must verify changed paths, parent commit and final ref. A successful file API response alone is not proof that the intended branch was changed.

**Status:** file removed from main by a normal revert, main tree content restored to the original baseline; commit history transparently preserves both the accidental add and its correction. This incident is a task-level execution failure and is included in the self-review; it must not be represented as a clean audit with no side effects.


## 17. Re-audit checkpoint — 2026-11-09 09:23 UTC

This checkpoint refreshes key facts against the current refs and provider state. It supersedes older point-in-time status values above where the same resource is rechecked.

### Repository refs and review evidence

- Current `main` is `b93f25e3df9f90baf1f25259a26df951919b9e7a`. Its tree SHA exactly matches the pre-incident baseline tree at `fe32bf8c9710c4c04308ad17f1876fa4f80c01a2`; GitHub compare reports two commits ahead, zero behind, and zero changed files. The accidental governance-document exposure and fast-forward revert remain in history; the tree is restored, but the incident is not erased.
- PR #199 remains OPEN / DRAFT / UNMERGED at head `c42a32237500a48b27828e0218e42b2642c883d3`. Its latest observed check-run set is 30 entries: 28 success and 2 skipped (`igor-independent`, `scorecard`). It has zero submitted reviews. Skipped checks are not passes; no independent-review condition is met.
- PR #189 remains OPEN / DRAFT at head `8e56b33df9a3e2806f3709fca90b07e4e595d28f`, 59 files, +7,148 / -557. Comparing this head with current `main` yields **122 commits ahead and 4 behind**. The PR is not a safe direct-merge candidate, notwithstanding GitHub's `mergeable_state=clean` result. Its 16 review submissions are all from one distinct human login, `krzys167-crypto`; independent accountability is unverified. Exact-head checks remain 38 success, 1 cancelled and 2 skipped.
- PR #190 remains OPEN / DRAFT at head `fbe2a19dc6c0a2a948f0a311cd7f91b798b97e07`; 26 checks passed and 3 were skipped. Its 38 review submissions come from one human login plus a security bot; there is no verified independent human reviewer.

### PR #190 — two OIDC approval/dispatch defects

The OIDC route in `app/main.py` obtains an active Human Identity operator, requires tenant equality, the `execution_approver` role, CSRF validation and a fresh authentication age, then calls `approve_paid_order()` with `approver_principal_id` and `approver_person_ref`.

The corresponding locked transaction in `app/order_approval.py` does **not** pass those two OIDC fields to its second `_validate_paid_order()` call. The preflight receives them, but the locked validation receives only `approver_id` and `tip_hash`. In the OIDC route, `approver_id` is intentionally absent; the second validation therefore falls into the legacy API-key branch and returns HTTP 400 (`legacy API approver identity is required`) before the approval evidence and outbox row are committed. This is a reproducible fail-closed functional defect, not an authorization bypass.

A second, downstream gap remains in `app/paid_order_execution.py`: `_execution_context()` checks `approver_id` against `control.approver_id`, but does not verify `approver_principal_id` or `approver_person_ref` against the corresponding Human Gate fields on the approval record/control row. OIDC approval fields therefore are not independently re-bound by the worker before dispatch. Correcting the locked call alone is insufficient; the worker must enforce the OIDC principal/person reference and requester/approver separation as part of its evidence checks.

The tests in `tests/test_paid_order_approval.py` exercise legacy API-key approvals and a deterministic end-to-end payment flow. `tests/test_human_gate_paid_order_routes.py` tests denial of API-key approval/review for OIDC_REQUIRED tenants and disables legacy JSON report retrieval, but contains no positive authenticated OIDC approval test. A new end-to-end test must prove a valid fresh OIDC operator can approve, that the same person cannot be requester/approver/reviewer, that locked revalidation preserves identity, and that the worker validates the recorded principal before execution.

### PR #189 — commercial and human-gate boundary

The legacy API approval path proves separation of two API-key IDs, not separation of two accountable humans. The successful test creates the approver API key without an explicit role (the model default is `tenant`) and the path accepts it; no `execution_approver` role or HR-backed person reference is required in this legacy branch. The newer OIDC_REQUIRED path is the intended higher-assurance alternative, but PR #190 has the defects above.

The worker calls NINA with the fixed `safe_expression` capability. The full paid-flow test explicitly asserts `invocation_type=local_deterministic_model` and `real_llm_invoked=false`, yet the execution status is `EXECUTED_REVIEW_REQUIRED` when the NINA/IGOR/provenance/replay checks pass. The worker's `checks_ok` predicate does not require a real LLM invocation. This is consistent with a **deterministic execution audit**; it is not evidence of a real external-LLM runtime audit. Any commercial offer that promises the latter needs a separate hard gate for provider, model, real invocation type and response IDs, and must fail closed on deterministic fallback.

### Railway staging — latest provider recheck

- Project `OLA FastAPI Staging`, environment `staging`, contains exactly one service: `ola-fastapi-api`. No separate worker service or cron is configured in this environment; the service's cron schedule is null.
- The live service configuration points to repo `krzysztofcieciwa07-ship-it/OLA`, branch `feat/ola-staging-bootstrap-20261108`, source SHA `393cc56dcd8c1a749cf11d4306d1e247144139cb`. The latest Railway deployment `4488f634-8212-4872-a287-d8074e8fe3e0` reports SUCCESS but its deployment metadata identifies SHA `030f7f1a4e18ba45da2cc9edbe530ffed92ee56`. GitHub compare confirms the configured source is three commits ahead of the deployed image. A successful deployment state does not reconcile this source/image mismatch.
- The deploy config has `sleepApplication=true`; the current status response reports no pending work, but no continuous replica/availability window was proven. Runtime logs show `OLA_POSTGRES_SCHEMA=VERIFIED`, startup and subsequent `GET /readyz 200` responses. The HTTP log also records a `/readyz` 499 with repeated `connection refused` upstream attempts at 09:12:47 UTC immediately after a container start, followed by 200 responses. This is transient cold-start/readiness evidence, not a sustained SLO pass.
- The complete service variable-name inventory includes `OLA_STAGING_BOOTSTRAP_SECRET`; values are redacted and no secret was decrypted. It is not listed as sealed, so its current non-empty/valid state is **UNKNOWN**. The inventory does **not** include `OLA_EXECUTION_WORKER_TOKEN`, `OLA_LLM_PROVIDER`, `OLA_LLM_MODE`, `OLLAMA_BASE_URL` or `OLLAMA_MODEL`.
- Given one API service, no scheduled worker and no worker-token variable, the connected Railway environment provides no evidence of an automated paid-order outbox consumer. Approved jobs may remain `QUEUED` until a separately authenticated worker is deployed/operated. No customer execution was initiated by this audit.

### PR #197 — Certificate Apocalypse further deterministic failures

The certificate generator sets SAN to `DNS:localhost,DNS:tls-under-test,IP:127.0.0.1`; the scenario's target hostname is `tls-target`. Even after the host/Docker DNS topology is fixed, strict hostname verification will reject the certificate for `tls-target` unless that SAN is added. The Compose file starts three containers (`tls-target`, `control-sentinel`, `chaos-runner`), while the assertion code currently requires exactly two. These are separate deterministic blockers behind the already-observed host-side DNS failure.

The public DSL field `private_assertion_policy=true` is not a hidden assertion implementation: the assertion code and contract tests are in the public PR branch. The score generator records missing evidence filenames in the manifest but does not independently fail solely because the manifest is incomplete. The workflow also lacks a failure bundle when readiness aborts before the report directory exists. Do not advertise private grading, anti-LLM protection or complete evidence capture from this implementation.

### Updated disposition

- #189: **NOT READY FOR MERGE** — divergent base, no verified independent review, API-key-only legacy SoD, no Railway worker, deterministic runtime not a real-LLM proof, and incomplete full paid-flow PostgreSQL coverage.
- #190: **BLOCKED** — locked OIDC revalidation omits principal/person reference; worker does not re-bind those fields; no positive OIDC approval test.
- #197: **FAIL / NOT RUNNABLE** — host-side DNS failure plus container-count and certificate-SAN blockers; no hidden private pack.
- #195 / staging: **STAGING SOURCE MISMATCH / WORKER NOT EVIDENCED** — successful deployment metadata does not match current configured source; one API service, no worker token; bootstrap secret state unknown.
- #199: **DRAFT / 28 PASS, 2 SKIPPED / ZERO REVIEWS** — documentation branch only; do not merge or describe as fully green.

No application code, payment, database record, service variable, deployment, branch protection or production setting was modified in this checkpoint. Only this audit documentation is being extended on the isolated governance branch.

 
## 18. Current-main and stale-PR findings — 2026-11-09

### Current main: /audit fails after the tenant already has evidence

The current-main implementation at app/main.py (b93f25e3df9f90baf1f25259a26df951919b9e7a) has a reproducible sequence-boundary defect in run_controlled_audit():

1. It appends five events by calling append_record() five times.
2. Each call delegates to append_evidence_atomic(), which commits its own independent transaction.
3. It then queries only the five new rows by evidence_ids and passes that subset to verify_chain().
4. The verifier starts from seq=0 and the genesis hash. For a tenant with any pre-existing evidence, the first selected new row has a non-zero sequence and a predecessor hash that is not genesis, so the subset fails with sequence or predecessor mismatch even though the full tenant chain may be valid.

This means a first audit on a fresh tenant can pass, but a subsequent audit (or the first audit after the tenant has any evidence) is expected to return status=FAILED. The current tests tests/test_product_e2e.py, tests/test_e2e.py and the runtime step in .github/workflows/e2e.yml all create a fresh tenant and run one audit; none seeds an earlier evidence record or invokes a second audit for that tenant.

There is also a partial-write risk: because the five append calls commit individually, a failure during event 2–5 leaves a partial audit event sequence in the append-only tenant ledger. There is no run-level transaction or explicit incomplete-run recovery state in this function.

**Required remediation (not performed):** verify the complete tenant chain after the appends, then select the audit's five event IDs for the report; add regression tests with an earlier public and privileged event plus two consecutive audits; make the audit group atomic where the DB supports it or explicitly model and recover incomplete audit runs. Do not weaken verify_chain() to accept arbitrary partial suffixes.

### Current main: the generic hash-chain verifier does not enforce one tenant per chain

Current app/hashchain.py binds each V2 hash to its own tenant_id, sequence, predecessor, record type and producer, but verify_chain() does not keep an expected_tenant_id and reject a later row from another tenant. A crafted ordered list whose records each have valid hashes and link to the prior record can therefore contain different tenant IDs and still pass the generic verifier.

Normal database reads in the reviewed application generally filter by tenant before calling the verifier, which reduces direct exposure through those call sites. The generic verifier itself nevertheless lacks a tenant-boundary invariant; this is the specific regression target of PR #91. The correct fix is a minimal same-tenant guard inside the current V2/V1-compatible verifier, not replacement with the old implementation from PR #91.

### Current main: IGOR can accept missing results and splice provenance fields

In current app/igor.py:

- A missing result can compare equal to an expected None because the code stringifies both sides (str(payload.get("result")) == str(expected_result)). A provenance/task-bearing event with no result can therefore satisfy the result check when the caller's expected result is None.
- Provider, model and response IDs are collected across a set of provenance events. Provider/invocation type may be satisfied by one record, model by another, and response IDs by a third. These fields are not required to coexist in one coherent trusted provenance record.

The verifier does reject non-trusted privileged events, so the fix must preserve current V2 producer/type trust checks while requiring a non-null expected result and a single coherent provenance object containing provider, model, invocation type and non-empty response IDs. This is the substantive intent of PR #92; its full branch must not be merged because it drops the existing trust boundary.

### PRs #91, #92 and #93 — valuable intent, unsafe stale implementations

All three PRs are based on old main SHA 1aadf7d2edc5abe345ec1d08a26d5331b51e5bc3. Current main has moved 43 commits beyond that base. Direct comparisons against current main show:

| PR | Head | Ahead of current main | Behind current main | Exact-head checks | Reviews |
|---|---|---:|---:|---|---|
| #91 | 543e4acc3a075e53ec999574b26a937e4b0eaba8 | 2 | 43 | 24 success, 2 skipped | 0 |
| #92 | 51ff6b3fe7ad5370d65e08e0db99bff15a7de2cc | 2 | 43 | 24 success, 2 skipped | 0 |
| #93 | d58199104e198cefab4ee5b95938deee98d366a6 | 3 | 43 | 24 success, 2 skipped | 0 |

The two skipped contexts on each exact head are igor-independent and scorecard; they are not passes.

**PR #91:** its proposed app/hashchain.py is an older V1-only verifier. It adds the tenant equality check but removes the current V2 metadata/type/producer binding, trusted_record(), domain-separated V2 hash verification and explicit legacy-read compatibility. Its tests use V1 compute_record_hash() fixtures, not V2 producer-bound evidence. Transplant only the tenant-ID invariant into the current V2 implementation and test both V2 and permitted legacy V1 records.

**PR #92:** its IGOR implementation adds a non-null expected-result guard and requires provider/model/response IDs to form a coherent provenance candidate, but removes trusted_record() and the is_privileged_type() gate. Its tests also build only V1 records. Transplant the two validation improvements into the current trusted-V2 path; add tests proving that public/untrusted records, legacy records and cross-record provenance splicing still BLOCK.

**PR #93:** the goal (narrow customer evidence namespace, reserved runtime fields, payload-size cap) is useful, but the candidate app/main.py is 43 commits behind current main and regresses multiple controls:
- it replaces the current api_key_fingerprint() (peppered scrypt) with plain SHA-256 for API-key lookup;
- it replaces atomic V2 evidence append with an old V1 append_record() implementation and omits the reserved __ola_evidence_v2__ metadata/producer protection;
- its /payment-success lookup again matches a completed StripeEvent by task text only, not by the exact checkout_session_id, reversing current main's session-bound customer-result protection;
- its added tests seed API keys using plain SHA-256, so they do not test the current scrypt-based authentication path and would need adaptation after a correct rebase.

Do not merge any of these PR branches as-is. Rebase narrowly, preserve present-day identity hashing, V2 producer binding, exact Stripe-session matching and existing API contracts, then prove the new regression tests on the rebased full suite.

### Updated disposition

- /audit on current main: **FUNCTIONAL DEFECT** for tenants with prior evidence; no multi-run test.
- verify_chain(): **TENANT-INVARIANT GAP** in generic verifier; preserve V2 when fixing.
- IGOR: **FAIL-CLOSED GAP** for null result and coherent provenance; preserve trusted producer checks.
- PR #91: **NO-GO AS-IS** — V1 downgrade.
- PR #92: **NO-GO AS-IS** — drops V2 producer trust.
- PR #93: **NO-GO AS-IS** — 43 commits behind; weakens API-key hashing, V2 writes and exact-session result binding.
- All three PRs have zero reviews and two skipped contexts on their exact heads.

No application code, main branch, database record, credential, deployment or repository setting was changed by this review.
