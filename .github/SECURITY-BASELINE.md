# OLA Repository Security Baseline

**Snapshot date:** 2026-11-09  
**Status:** HARDENING IN PROGRESS — NOT CERTIFIED  
**Scope:** Repository governance and engineering controls for OLA. This document is not a security certification, legal opinion, NIS2 applicability determination, or proof of production readiness.

## 1. Assurance target and legal boundary

The engineering baseline is being mapped to the **CCB CyberFundamentals Framework, CyFun 2025, Essential assurance level** as a deliberately high target for a system intended to support high-trust environments.

This target does **not** mean that OLA, its developer, this repository, or any customer deployment is CyFun-certified. Certification or conformity assessment applies to a defined organisation and scope and must be independently assessed through the applicable accredited route.

NIS2 applicability must be assessed for the actual operator, entity type, services and size. Do not describe every public administration as automatically subject to NIS2. The CCB's public-sector FAQ distinguishes local administrations from federal and federated public administrations and identifies specific scope and designation conditions.

Reference framework:
- CCB, [CyFun 2025 announcement](https://ccb.belgium.be/news/cyfunr-2025-here).
- CCB, [Government cybersecurity and CyFun assurance levels](https://ccb.belgium.be/government).
- CCB, [NIS2 FAQ — public sector](https://ccb.belgium.be/sites/default/files/2025-02/NIS2%20FAQ%20Website%20v2.0.1%20EN.pdf).
- GitHub, [available rules for repository rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
- GitHub, [secure use of GitHub Actions](https://docs.github.com/en/actions/reference/security/secure-use).

## 2. Evidence semantics

Every control is recorded as one of:

- `PASS` — verified against the exact account, repository, branch, commit, workflow run or deployment scope.
- `FAIL` — verified and not satisfied.
- `UNKNOWN` — evidence is unavailable, incomplete, stale or not independently checked.
- `NOT_APPLICABLE` — scope decision documented with its rationale and owner.

A workflow file existing is not a passing check. A skipped check is not a pass. A check on a different SHA is not evidence for the SHA under review. A locally reproducible test is not a production deployment proof.

## 3. Verified repository snapshot — 2026-11-09

Repository: `krzysztofcieciwa07-ship-it/OLA`  
Default branch: `main`  
Reviewed main SHA: `fe32bf8c9710c4c04308ad17f1876fa4f80c01a2`

Observed:
- 166 branches.
- 76 open pull requests, 64 of them Draft.
- Several branch names point to identical commit SHAs; duplicate names must be reconciled against PR references and unique commits before any deletion.
- An active repository ruleset named `SECURITY.md` exists. Its inspected rules prohibit branch deletion and non-fast-forward updates. It does not require pull-request approval or successful status checks.
- The branch-protection endpoint could not be read using the current integration. Other classic branch-protection settings therefore remain `UNKNOWN`.
- The current main SHA had 37 check-run records. The latest result per distinct check name contained 30 successes, 2 failures and 1 skipped result. This is not an all-green baseline.
- Secret scanning, push protection, Dependabot alert state, repository Actions permissions, environment protection and account MFA state were not fully verifiable through the available integration.

Do not apply a required-check ruleset using stale check names or a stale SHA. The existing `scripts/apply_main_ruleset.py` contains a static check-context list tied to a previously observed SHA. It must be reconciled with current check names, optional/conditional jobs, failure handling and exact-SHA behaviour before it is used.

## 4. Required account and identity controls

Before describing this portfolio as suitable for government or other high-trust procurement:

1. Require phishing-resistant MFA for every human maintainer where supported; prefer passkeys or hardware security keys. Protect recovery methods separately.
2. Do not share accounts or recovery credentials.
3. Maintain at least two separately accountable administrators/recovery paths for the product organisation, with least privilege and auditable ownership. A second person must be a real, trusted reviewer — never a placeholder account.
4. Use an organisation for product-owned repositories when legal ownership and a second administrator are established. Keep unrelated upstream forks outside the product's canonical project surface.
5. Review GitHub App installations, repository-selection scope, OAuth grants, fine-grained PATs, deploy keys, webhooks and collaborator access. Narrow integrations to the smallest repository set and permissions required.
6. Keep account-level audit and security-log retention appropriate to the deployment's risk and contractual requirements.

Account settings that cannot be read by the connected integration remain `UNKNOWN` until the owner verifies them directly.

## 5. Required protection for `main`

The target policy for each canonical product repository is:

- Require pull requests; prohibit direct pushes to release branches.
- Require at least one approval from a person other than the PR author and the most recent pusher.
- Dismiss stale approvals when the diff changes.
- Require all review threads to be resolved.
- Require CODEOWNERS review for critical paths after genuine independent owners have been assigned.
- Require successful, stable, exact-SHA CI checks from the intended GitHub App.
- Block force pushes and branch deletion.
- Require signed commits where the signing identity and recovery process are operationally supported.
- Configure no routine bypass actors. Any emergency bypass must be separately approved, time-bounded, logged and reviewed.
- Use merge queue or strict up-to-date policy where the chosen workflow supports it.

**Activation blocker:** the independent reviewer identity and the exact stable required-check set are not yet established by the current evidence. Do not set a fictitious reviewer, require a stale list of checks, or apply a ruleset that makes the branch appear protected while omitting actual failures.

GitHub documents that review counts, code-owner review and required status checks are separate rules. A CODEOWNERS file alone does not enforce any of them.

## 6. CI/CD and automation controls

- Default workflow permissions to read-only. Grant write permissions only to the individual job that needs them.
- Pin third-party Actions to full-length commit SHAs or use a verified workflow dependency lockfile. Review the source of every third-party action.
- Use `persist-credentials: false` on checkout unless the job genuinely requires authenticated Git operations.
- Never expose deployment secrets to untrusted fork pull requests or untrusted pull-request code.
- Prefer workload identity/OIDC and short-lived credentials over long-lived static credentials.
- Separate build, test, release and deployment identities. Production deployment requires an explicit protected-environment approval.
- Avoid duplicate workflows. Map current triggers, permissions, outputs, check names, skip conditions and failure semantics before adding or replacing CI.
- No workflow may promote `UNKNOWN`, `SKIPPED`, `PARTIAL` or unverified fallback execution to `PASS` or `VERIFIED`.

## 7. Software supply-chain controls

For each release candidate:
- Lock application dependencies and review vulnerability alerts.
- Produce an SBOM for the source/dependency set and the release artifact.
- Run secret scanning, static analysis, dependency review and workflow linting.
- Bind build provenance to the exact source commit and immutable artifact digest.
- Verify attestations independently before release promotion.
- Sign release artifacts where supported; keep signing keys outside the repository and record key custody/rotation procedures.
- Preserve the source SHA, workflow run IDs, check conclusions, artifact digests, attestations and approval record.

A signed build attestation proves a defined build relationship; it does not prove the application is secure or that a deployment is compliant.

## 8. Secrets and data handling

- Commit only documented placeholders in `.env.example`; never commit real `.env` files, private keys, signing material, tokens, customer data or production evidence.
- Enable secret scanning and push protection where available; keep a second independent scanner in CI for repository content and history.
- Scan current refs and full Git history before public release. Do not print detected secret values in logs or reports.
- Treat every confirmed exposure as an incident: identify provider and privilege, revoke/rotate, inspect use, preserve evidence, and verify that the old credential no longer works.
- Classify evidence artifacts as potentially sensitive. Hashing does not provide confidentiality.

## 9. Repository lifecycle and change control

Every repository must have:
- one canonical owner and purpose;
- explicit product classification (`CORE`, `ACTIVE`, `EXPERIMENTAL`, `UPSTREAM_FORK`, `SPEC`, `ARCHIVE_CANDIDATE` or `UNKNOWN`);
- a truthful description, homepage and topics;
- a supported default branch;
- a security policy and vulnerability-reporting route;
- an owner/reviewer map;
- a current ruleset and CI-control record;
- an inventory of forks, branches, open PRs and release references.

No repository, branch, tag, issue, PR or history may be deleted or transferred solely because its name appears duplicated. Compare immutable SHAs, Git ancestry, unique commits, open PRs, release assets and external dependencies first.

## 10. Acceptance gate for a high-trust release

A release cannot be called `VERIFIED` until all applicable items below are evidenced for the exact release candidate:

1. account identity, MFA and administrator access reviewed;
2. canonical repository, protected branch and independent review established;
3. exact-SHA required checks passed; no unexplained failures or skipped mandatory checks;
4. secret and dependency scans completed with findings triaged;
5. build provenance and artifact digest independently verified;
6. runtime deployment and health observed in the target environment;
7. tenant/access-isolation and security tests passed;
8. evidence integrity, provenance and replay checks passed;
9. recovery, rollback and incident procedures tested;
10. human release authorisation recorded.

The absence of any required proof leaves the gate `BLOCKED` or `UNKNOWN`, not `VERIFIED`.

## 11. Current decision

**Current status: HARDENING IN PROGRESS / NOT CERTIFIED / PRODUCTION SECURITY POSTURE UNKNOWN.**

The first remediation tranche is repository and account governance. Feature work must not outrank resolution of canonical ownership, account access scope, independent review, exact-SHA check inventory and main-branch enforcement.
