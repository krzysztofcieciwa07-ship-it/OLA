# OLA Product Portfolio — Repository Register

**Snapshot:** 2026-11-09  
**Purpose:** establish one truthful map of the repositories that may represent OLA and adjacent products.  
**Evidence boundary:** GitHub metadata, default-branch trees, selected READMEs, branch lists and commit comparisons. The two GitHub logins are technically separate; this register does not prove that the same legal person owns or controls both accounts.

## 1. Canonical product map — proposed, not yet transferred

| Product / role | Repository | Observed content | Current decision |
|---|---|---|---|
| OLA runtime | [krzysztofcieciwa07-ship-it/OLA](https://github.com/krzysztofcieciwa07-ship-it/OLA) | Python/FastAPI runtime, NINA orchestration, IGOR verification, tenant-scoped SQLite evidence, replay, Human Gate model, Stripe paths, tests and CI workflows. | **CORE — temporary canonical source** pending reconciliation with the other OLA repository. |
| OLA divergent fork | [krzys167-crypto/OLA](https://github.com/krzys167-crypto/OLA) | 260-file tree including `ola_pipeline/`, CFR scenarios, sales material, tools and additional tests. GitHub API confirms `fork=true`, parent/source `krzysztofcieciwa07-ship-it/OLA`. | **FORK OF CORE — HISTORY TO RECONCILE**. It is not an independent canonical repo, but its divergent commits may contain unique work. Current integration has read-only access. |
| Vantage incident range | [krzys167-crypto/Vantage-v0.3](https://github.com/krzys167-crypto/Vantage-v0.3) | Approximately 180 tracked files in the current default branch; DSL v0, Docker/k3d, Certificate Apocalypse, Clock Drift, Split-Brain DNS, Retry Storm, grader, signed scoring and debrief workflows. | **CORE CANDIDATE — OWNERSHIP/ADMIN CONTROL UNVERIFIED**. Default branch is currently named `claude/powershell-install-script-h86qlw`, not `main`. Do not present as a company-owned asset until authority is verified. |
| Vantage prototype | [krzysztofcieciwa07-ship-it/vantage](https://github.com/krzysztofcieciwa07-ship-it/vantage) | Small Python risk-gate/LLM-routing prototype with a separate CFR-18 exercise. Its README explicitly classifies it as a prototype. | **EXPERIMENTAL**. Do not present as the same implementation as Vantage v0.3. |
| Quantum app | [krzysztofcieciwa07-ship-it/quantum-ai-chatbot](https://github.com/krzysztofcieciwa07-ship-it/quantum-ai-chatbot) | Mobile-first React/Vite app, Supabase, chat history, server-side API routes, Google/Microsoft connector code and security policy tests. | **EXPERIMENTAL / ADJACENT PRODUCT**. Separate from OLA core; connector security review remains open. |
| Older Quantum source | [krzys167-crypto/quantum-ai-chatbot](https://github.com/krzys167-crypto/quantum-ai-chatbot) | Older version with the same general application. Its `.env` is tracked in current main history. The token examined was a Supabase `anon` key, not `service_role`. | **LEGACY SOURCE**. Do not use as the public showcase copy. The newer `ship-it` main is four commits ahead and removes `.env`. |
| Evidence Gateway | [krzysztofcieciwa07-ship-it/ola-evidence-gateway](https://github.com/krzysztofcieciwa07-ship-it/ola-evidence-gateway) | Current main has 3 files, including README and editor/devcontainer configuration; no gateway implementation or tests. Homepage points to an unrelated weather site. | **SPEC / ARCHIVE CANDIDATE**. Do not describe as a working service. |
| OLA AI Plugins | [krzys167-crypto/Ola-ai-plugins](https://github.com/krzys167-crypto/Ola-ai-plugins) | One README describing the OLA Evidence concept; no plugin implementation. | **SPEC**. Consolidate useful material into OLA documentation. |

## 2. Material repository divergence

### OLA

GitHub repository metadata identifies `krzys167-crypto/OLA` as a fork of `krzysztofcieciwa07-ship-it/OLA` (parent/source confirmed by API). The two histories share merge base `a59f8c12f8120a13cfe2627dfa9946d61a9116b8`, but are substantially divergent:

- `krzysztofcieciwa07-ship-it/OLA` main: `fe32bf8c9710c4c04308ad17f1876fa4f80c01a2`.
- `krzys167-crypto/OLA` main: `d2dd11c8dd964d4c846bcab4e74b2d02b77a9f4a`.
- Relative to the second repository's main, ship-it is 56 commits ahead and 235 commits behind.

This is not a safe fast-forward or simple mirror update. Build a commit-level migration matrix, identify unique security and product changes, port selected commits by reviewed PR, and keep both histories intact until reconciliation is independently accepted.

### Vantage

The 0.3 implementation is on `krzys167-crypto/Vantage-v0.3`. The private `krzysztofcieciwa07-ship-it/Vantage-v0.3` repository is empty (0 KB) and has no branches in the observed listing. Do not call the empty repository the implementation source.

The separate `ship-it/vantage` prototype is not a substitute for Vantage v0.3. The small `krzys167-crypto/vantage` fork is one commit behind `ship-it/vantage` and should not be presented as a separate product.

### Quantum

The newer `ship-it` copy has four commits not present in the older account's main. The comparison includes removing `.env`, tightening the execution policy and adding a security workflow/test. The older repository's `.env` has only a Supabase `anon` key in the inspected version; this is a public client key, not an administrative service-role key. It should still not be committed as an environment file.

## 3. Connected account — `krzysztofcieciwa07-ship-it`

The linked GitHub identity exposes 10 repositories owned by this user account and no organisation memberships:

| Repository | Visibility | Default branch | Branches | Fork relationship | Proposed classification |
|---|---|---|---:|---|---|
| `OLA` | public | `main` | 167 | original | CORE |
| `vantage` | public | `main` | 27 | original | EXPERIMENTAL |
| `Vantage-v0.3` | private | `main` | 0 | original, empty | ARCHIVE CANDIDATE |
| `quantum-ai-chatbot` | public | `main` | 2 | fork of `krzys167-crypto/quantum-ai-chatbot` | EXPERIMENTAL |
| `ola-evidence-gateway` | public | `main` | 4 | fork of `krzys167-crypto/ola-evidence-gateway` | SPEC |
| `MetaGPT` | public | `main` | 1 | fork of `FoundationAgents/MetaGPT` | UPSTREAM FORK |
| `cli` | public | `trunk` | 1 | fork of `cli/cli` | UPSTREAM FORK |
| `ai` | public | `main` | 1 | fork of `vercel/ai` | UPSTREAM FORK |
| `uygulamali-kriptografi` | public | `master` | 1 | fork of `hnfgns/uygulamali-kriptografi` | UPSTREAM FORK |
| `swarmclaw` | public | `main` | 1 | fork of `octo-patch/swarmclaw` | UPSTREAM FORK |

**Total on this connected account: 10 repositories and 205 branch refs.** The OLA count includes the governance branch created for PR #199.

## 3.1 Live PR and branch hygiene snapshot

The 2026-11-09 API snapshot shows 167 branches and 77 open PRs (65 Draft, 12 ready). Forty-two open PRs have not been updated for more than 14 days; seven have not been updated for more than 30 days. Use age only to prioritise review, not as an automatic reason to close. Triage each PR into **MERGE CANDIDATE**, **SUPERSEDED**, **BLOCKED**, or **CLOSE WITH REASON**. The row-level snapshot is in [OPEN-PR-TRIAGE-2026-11-09.csv](OPEN-PR-TRIAGE-2026-11-09.csv); all 77 entries begin as `UNREVIEWED` and require an explicit disposition.

For the governance PR itself, commit `56185487aca8879197b2a71897e0082f799fce56` had 29 latest check contexts at snapshot: 27 succeeded and 2 were skipped. The skipped contexts are not passes. No PR review had been submitted. This is not a merge approval.

### OLA branch shape

The 167 OLA branch refs are distributed as follows:

| Prefix / group | Branches |
|---|---:|
| `fix/*` | 45 |
| `feat/*` | 33 |
| `security/*` | 21 |
| Unprefixed names | 18 |
| `integration/*` | 14 |
| `docs/*` | 5 |
| `hardening/*` | 4 |
| `ops/*` | 4 |
| `ui/*` | 3 |
| `chore/*` | 3 |
| `codex/*` | 2 |
| `integrate/*` | 2 |
| `governance/*` | 2 |
| Other single-branch prefixes | 11 |

Live branch and pull-request audit (2026-11-09):
- Branch API returned **167** branch refs across two pages.
- GitHub returned **77 open pull requests**: **65 Draft** and **12 ready for review**.
- **42** open PRs had not been updated in more than 14 days; **7** had not been updated in more than 30 days. These are triage candidates, not automatic close candidates.
- Current open-PR distribution includes new work (#199, #198, #197, #195–#189) and older work that needs a disposition decision. Every PR must be classified as merge candidate, superseded, blocked, or close-with-reason; age alone is not a closure rule.

**Duplicate branch HEAD groups observed in the live branch list**

| Shared HEAD SHA | Branches | Open-PR association | Decision |
|---|---|---|---|
| `6dff9c43ccd5a6892a50d1f59363d232b07ceafb` | `feat/ola-staging-bff-bootstrap-clean-20261108`; `integration/jev-decision-fabric-20261106` | No open PR directly uses either branch as its head. | Candidate for dependency/history review. |
| `8e56b33df9a3e2806f3709fca90b07e4e595d28f` | `feat/runtime-image-attestation-20261107`; `integration/ola-first-five-closure-20261106`; `integration/replit-bff-recovery-20261107` | `integration/ola-first-five-closure-20261106` is the head of open PR **#189**. | **KEEP** until PR #189 is resolved and all consumers are checked. |
| `c87cb3c8a798fece4ee18f73ecc648e397b23c24` | `fix/agent-runtime-minimal-2`, `-3`, `-4`, `-5`, `-7`, `-8`, `-9`, `-10`, `-11` | No open PR directly uses these branch names as its head. | High-priority candidate group for dependency/history review; preserve until checked. |
| `3f39ff8c1b705b501d86fcfa9572604596906e65` | `fix/agent-runtime-source-binding-20261105`; `verify/pr170-final-head-20261105` | No open PR directly uses either branch as its head. | Candidate for dependency/history review. |
| `9990e9f990cee87bc0d00c5c99566d4e436238f0` | `fix/final-production-gate-20261006`; `fix/final-production-gate-stage-20261006` | No open PR directly uses either branch as its head. | Candidate for dependency/history review. |

Identical HEADs prove only that the refs currently point to the same commit. They do **not** prove the names are disposable: another PR may use a branch as a base, workflow or deployment may reference it, or branch history may need to remain for traceability. Before any deletion, inspect every open and closed PR's head/base refs, commit ancestry, workflow references and deployment configuration. The active OLA ruleset currently prohibits branch deletion, so deletion is not currently available under the observed policy.

Branch browser: [all OLA branches](https://github.com/krzysztofcieciwa07-ship-it/OLA/branches/all) · [open OLA pull requests](https://github.com/krzysztofcieciwa07-ship-it/OLA/pulls)

Several product repositories have empty GitHub descriptions/topics. Repository metadata should be applied only after this classification and the canonical source decisions are accepted.

## 4. Second public login — `krzys167-crypto`

A public repository search surfaced 32 repositories under this separate login. The current GitHub integration has read-only permission there. The list below is an inventory of public repository names, not proof of common ownership.

**Complete repository and branch-count inventory**

| Repository | Branches | Observed branch names when count is greater than 1 | Classification |
|---|---:|---|---|
| `agent-os` | 1 | — | UPSTREAM FORK |
| `awesome-python` | 2 | `Ola-agent-firewall`, `master` | UPSTREAM FORK |
| `MoneyPrinterTurbo` | 1 | — | UPSTREAM FORK |
| `uygulamali-kriptografi` | 1 | — | UPSTREAM FORK |
| `quantum-ai-chatbot` | 7 | `main`, `fix/f09-server-side-approval`, `fix/oauth-state-token-hardening`, `port/combined-on-d74d883`, `port/extras-on-d74d883`, `port/pr1-on-d74d883`, `port/pr2-on-d74d883` | LEGACY SOURCE |
| `ola-evidence-gateway` | 5 | `main`, `automation/evidence-v0.1`, two Codespaces branches, one revert branch | SPEC |
| `CLI-Anything` | 1 | — | UPSTREAM FORK |
| `ai` | 2 | `main`, `krzys167-crypto-patch-1` | UPSTREAM FORK |
| `swarmclaw` | 1 | — | UPSTREAM FORK |
| `goalfloow` | 1 | — | UPSTREAM FORK; tracked `.env` to review |
| `dotfiles` | 1 | — | UPSTREAM FORK |
| `brew` | 1 | — | UPSTREAM FORK |
| `Vantage-v0.3` | 15 | 13 `claude/*` branches, `main`, `revert-21-main`; default branch is `claude/powershell-install-script-h86qlw` | CORE CANDIDATE |
| `arrow` | 1 | — | UPSTREAM FORK |
| `community` | 2 | `main`, `krzys167-crypto-patch-1` | UPSTREAM FORK |
| `django-ai-plugins` | 1 | — | UPSTREAM FORK |
| `congress-tracker` | 1 | — | UPSTREAM FORK |
| `avalanche-react` | 1 | — | UPSTREAM FORK |
| `RobynAwesome` | 1 | — | UPSTREAM FORK |
| `MetaGPT` | 1 | — | UPSTREAM FORK |
| `Ola-ai-plugins` | 5 | `main`, `automation/evidence-v0.1`, three Vercel branches | SPEC |
| `vantage` | 2 | `main`, `patch-1` | UPSTREAM FORK of ship-it prototype |
| `OLA` | 88 | 88 refs including `main`, `cfr18-forensic`, multiple `feat/*`, `fix/*`, `security/*`, `integration/*`, and `ui/*` | DIVERGENT SOURCE |
| `google-api-nodejs-client` | 1 | — | UPSTREAM FORK |
| `cli` | 1 | — | UPSTREAM FORK |
| `docs` | 1 | — | UPSTREAM FORK |
| `TIMEATLAS` | 1 | — | UNKNOWN |
| `house-documents` | 1 | — | UPSTREAM FORK |
| `homebrew-cask` | 1 | — | UPSTREAM FORK |
| `vigilant-fiesta` | 1 | — | UNKNOWN |
| `ola.dios.audit-gmail.com` | 1 | — | ADJACENT FORK — ownership/purpose to confirm |
| `homebrew-core` | 1 | — | UPSTREAM FORK |

**Total under this separate public login: 32 repositories and 150 branch refs.** Together, the two public logins expose 42 repositories and 355 branch refs. These remain separate GitHub identities; common ownership is not established by this audit. Counts are from the branch API listing; the larger branch inventories are recorded by count and key branch patterns rather than copying every ref into this document.

Branch browsers: [second-account OLA branches](https://github.com/krzys167-crypto/OLA/branches/all) · [Vantage v0.3 branches](https://github.com/krzys167-crypto/Vantage-v0.3/branches/all) · [Quantum branches](https://github.com/krzys167-crypto/quantum-ai-chatbot/branches/all)

**OLA/Vantage-related findings**
- `OLA` is a divergent source from the ship-it repository, not a mirror.
- `Vantage-v0.3` is the developed incident-response range. Its default branch is not `main`.
- `vantage` is a one-commit-behind fork of the ship-it prototype, not a second independent Vantage product.
- `quantum-ai-chatbot` is the older source and includes a tracked `.env` in its main history. The inspected token was a Supabase `anon` key, not `service_role`.
- `ola-evidence-gateway` and `Ola-ai-plugins` contain README-level specifications rather than working services.
- `ola.dios.audit-gmail.com` is a small fork whose purpose and product ownership still require confirmation.
- `goalfloow` is an unrelated upstream fork; the inspected `.env` contains a public Supabase `anon` key. No `service_role` claim was confirmed.



## 5. GitHub governance snapshot

The following is the repository-level ruleset evidence visible through the current integration. A missing ruleset result does not by itself prove that no classic branch-protection rule exists; where the protection endpoint was unavailable, classic protection remains `UNKNOWN`.

| Repository | Visible ruleset evidence | Branches observed | Assessment |
|---|---|---:|---|
| `ship-it/OLA` | Active `SECURITY.md` ruleset; inspected rules only prevent deletion and non-fast-forward updates. No approval count or required status checks. | 167 | **FAIL** against the target baseline. |
| `ship-it/vantage` | No repository ruleset returned. | 27 | **UNKNOWN / FAIL** — no visible ruleset; classic protection not verified. |
| `ship-it/quantum-ai-chatbot` | No repository ruleset returned. | 2 | **UNKNOWN / FAIL** — no visible ruleset; classic protection not verified. |
| `ship-it/ola-evidence-gateway` | No repository ruleset returned. | 4 | **UNKNOWN / FAIL** — no visible ruleset; classic protection not verified. |
| `ship-it/Vantage-v0.3` | Private empty repository; no branches observed. | 0 | No active implementation to protect. |
| `krzys167-crypto/OLA` | No repository ruleset returned. | 88 | **UNKNOWN** — read-only connection; classic protection not verified. |
| `krzys167-crypto/Vantage-v0.3` | Active ruleset named `ola di-os`. Pull-request approval count is 0 and required status-check list is empty. It includes code-owner review, but no `.github/CODEOWNERS` file was found on the inspected `main` ref. | 15 | **FAIL** against the target baseline despite the long ruleset. |
| `krzys167-crypto/quantum-ai-chatbot` | No repository ruleset returned. | 7 | **UNKNOWN** — older read-only copy. |
| `krzys167-crypto/ola-evidence-gateway` | No repository ruleset returned; `main` was marked protected by the branch listing. | 5 | **PARTIAL / UNKNOWN** — branch protection exists, full required rules not verified. |

### Required interpretation

- A ruleset name such as `SECURITY.md` or `ola di-os` is not proof of a secure merge policy.
- A pull-request rule with `required_approving_review_count: 0` does not establish independent review.
- A required-status-check rule with an empty check list does not block on any named CI context.
- CODEOWNERS review without an independently assigned owner/reviewer does not establish separation of duties.
- Branch API `protected=false` is not conclusive where classic branch-protection access is unavailable; retain `UNKNOWN` until the complete effective policy is verified.

## 6. Repository metadata proposals

Canonical public descriptions and topics are proposed in [REPOSITORY-METADATA.md](REPOSITORY-METADATA.md). Repository descriptions, homepage, topics, visibility, transfers and archiving have **not** been changed by this register.

A full evidence-based security and hygiene review is in [PORTFOLIO-AUDIT-2026-11-09.md](PORTFOLIO-AUDIT-2026-11-09.md). It includes critical Quantum/Vantage findings and controls that remain UNKNOWN.

## 7. Canonicalisation decisions still required

1. Confirm `ship-it/OLA` as the only canonical OLA write target after a reviewed migration of the unique commits from the second OLA.
2. Obtain owner-authorised write access to `krzys167-crypto/Vantage-v0.3` or agree on a controlled transfer/mirror. Do not attempt to rewrite it from the read-only connection.
3. Decide whether `ship-it/vantage` remains an experimental prototype or is retired after Vantage v0.3 is safely consolidated.
4. Keep Quantum separate until OAuth, token storage, session binding, scope minimisation and disconnect/revocation findings are resolved.
5. Fold Evidence Gateway and OLA AI Plugins specifications into OLA docs unless a real, independently tested service is built.
6. Classify remaining forks and dormant repositories as `UPSTREAM_FORK`, `EXPERIMENTAL`, `ARCHIVE CANDIDATE` or `UNKNOWN` only after reviewing their local commits and dependencies.

**No repository, branch, tag, file history, issue, release or asset was deleted or transferred as part of this inventory.**
