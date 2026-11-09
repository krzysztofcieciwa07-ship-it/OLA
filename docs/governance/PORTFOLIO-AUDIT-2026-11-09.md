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
