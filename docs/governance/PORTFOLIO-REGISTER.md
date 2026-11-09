# OLA Product Portfolio — Repository Register

**Snapshot:** 2026-11-09  
**Purpose:** establish one truthful map of the repositories that may represent OLA and adjacent products.  
**Evidence boundary:** GitHub metadata, default-branch trees, selected READMEs, branch lists and commit comparisons. The two GitHub logins are technically separate; this register does not prove that the same legal person owns or controls both accounts.

## 1. Canonical product map — proposed, not yet transferred

| Product / role | Repository | Observed content | Current decision |
|---|---|---|---|
| OLA runtime | [krzysztofcieciwa07-ship-it/OLA](https://github.com/krzysztofcieciwa07-ship-it/OLA) | Python/FastAPI runtime, NINA orchestration, IGOR verification, tenant-scoped SQLite evidence, replay, Human Gate model, Stripe paths, tests and CI workflows. | **CORE — temporary canonical source** pending reconciliation with the other OLA repository. |
| OLA divergent source | [krzys167-crypto/OLA](https://github.com/krzys167-crypto/OLA) | 260-file tree including `ola_pipeline/`, CFR scenarios, sales material, tools and additional tests. | **SOURCE TO RECONCILE**. Not a second canonical product. Current integration has read-only access. |
| Vantage incident range | [krzys167-crypto/Vantage-v0.3](https://github.com/krzys167-crypto/Vantage-v0.3) | Approximately 180 tracked files in the current default branch; DSL v0, Docker/k3d, Certificate Apocalypse, Clock Drift, Split-Brain DNS, Retry Storm, grader, signed scoring and debrief workflows. | **CORE CANDIDATE** for Vantage v0.3. Default branch is currently named `claude/powershell-install-script-h86qlw`, not `main`. |
| Vantage prototype | [krzysztofcieciwa07-ship-it/vantage](https://github.com/krzysztofcieciwa07-ship-it/vantage) | Small Python risk-gate/LLM-routing prototype with a separate CFR-18 exercise. Its README explicitly classifies it as a prototype. | **EXPERIMENTAL**. Do not present as the same implementation as Vantage v0.3. |
| Quantum app | [krzysztofcieciwa07-ship-it/quantum-ai-chatbot](https://github.com/krzysztofcieciwa07-ship-it/quantum-ai-chatbot) | Mobile-first React/Vite app, Supabase, chat history, server-side API routes, Google/Microsoft connector code and security policy tests. | **EXPERIMENTAL / ADJACENT PRODUCT**. Separate from OLA core; connector security review remains open. |
| Older Quantum source | [krzys167-crypto/quantum-ai-chatbot](https://github.com/krzys167-crypto/quantum-ai-chatbot) | Older version with the same general application. Its `.env` is tracked in current main history. The token examined was a Supabase `anon` key, not `service_role`. | **LEGACY SOURCE**. Do not use as the public showcase copy. The newer `ship-it` main is four commits ahead and removes `.env`. |
| Evidence Gateway | [krzysztofcieciwa07-ship-it/ola-evidence-gateway](https://github.com/krzysztofcieciwa07-ship-it/ola-evidence-gateway) | Current main has 3 files, including README and editor/devcontainer configuration; no gateway implementation or tests. Homepage points to an unrelated weather site. | **SPEC / ARCHIVE CANDIDATE**. Do not describe as a working service. |
| OLA AI Plugins | [krzys167-crypto/Ola-ai-plugins](https://github.com/krzys167-crypto/Ola-ai-plugins) | One README describing the OLA Evidence concept; no plugin implementation. | **SPEC**. Consolidate useful material into OLA documentation. |

## 2. Material repository divergence

### OLA

The two OLA repositories share merge base `a59f8c12f8120a13cfe2627dfa9946d61a9116b8`, but are substantially divergent:

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

| Repository | Visibility | Default branch | Fork relationship | Proposed classification |
|---|---|---|---|---|
| `OLA` | public | `main` | original | CORE |
| `vantage` | public | `main` | original | EXPERIMENTAL |
| `Vantage-v0.3` | private | `main` | original, empty | ARCHIVE CANDIDATE |
| `quantum-ai-chatbot` | public | `main` | fork of `krzys167-crypto/quantum-ai-chatbot` | EXPERIMENTAL |
| `ola-evidence-gateway` | public | `main` | fork of `krzys167-crypto/ola-evidence-gateway` | SPEC |
| `MetaGPT` | public | `main` | fork of `FoundationAgents/MetaGPT` | UPSTREAM FORK |
| `cli` | public | `trunk` | fork of `cli/cli` | UPSTREAM FORK |
| `ai` | public | `main` | fork of `vercel/ai` | UPSTREAM FORK |
| `uygulamali-kriptografi` | public | `master` | fork of `hnfgns/uygulamali-kriptografi` | UPSTREAM FORK |
| `swarmclaw` | public | `main` | fork of `octo-patch/swarmclaw` | UPSTREAM FORK |

Several product repositories have empty GitHub descriptions/topics. Repository metadata should be applied only after this classification and the canonical source decisions are accepted.

## 4. Second public login — `krzys167-crypto`

A public repository search surfaced 32 repositories under this separate login. The current GitHub integration has read-only permission there. The list below is an inventory of public repository names, not proof of common ownership.

**OLA/Vantage-related repositories or adjacent forks**
- `OLA` — divergent OLA source.
- `Vantage-v0.3` — developed incident-response range.
- `vantage` — small fork of `ship-it/vantage`.
- `quantum-ai-chatbot` — older Quantum source.
- `ola-evidence-gateway` — README-only specification.
- `Ola-ai-plugins` — README-only specification.
- `ola.dios.audit-gmail.com` — small fork; purpose and ownership require confirmation.

**Independent or currently unclassified repositories**
- `TIMEATLAS`
- `vigilant-fiesta`

**Upstream/reference forks — do not present as proprietary OLA products**
- `agent-os`
- `awesome-python`
- `MoneyPrinterTurbo`
- `uygulamali-kriptografi`
- `CLI-Anything`
- `ai`
- `swarmclaw`
- `goalfloow` — contains a tracked `.env` with a public Supabase `anon` key; no `service_role` claim was confirmed.
- `dotfiles`
- `brew`
- `arrow`
- `community`
- `django-ai-plugins`
- `congress-tracker`
- `avalanche-react`
- `RobynAwesome`
- `MetaGPT`
- `google-api-nodejs-client`
- `cli`
- `docs`
- `house-documents`
- `homebrew-cask`
- `homebrew-core`

Some forks may contain local changes or useful research. They remain upstream forks unless a distinct, original product contribution is demonstrated.

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

## 7. Canonicalisation decisions still required

1. Confirm `ship-it/OLA` as the only canonical OLA write target after a reviewed migration of the unique commits from the second OLA.
2. Obtain owner-authorised write access to `krzys167-crypto/Vantage-v0.3` or agree on a controlled transfer/mirror. Do not attempt to rewrite it from the read-only connection.
3. Decide whether `ship-it/vantage` remains an experimental prototype or is retired after Vantage v0.3 is safely consolidated.
4. Keep Quantum separate until OAuth, token storage, session binding, scope minimisation and disconnect/revocation findings are resolved.
5. Fold Evidence Gateway and OLA AI Plugins specifications into OLA docs unless a real, independently tested service is built.
6. Classify remaining forks and dormant repositories as `UPSTREAM_FORK`, `EXPERIMENTAL`, `ARCHIVE CANDIDATE` or `UNKNOWN` only after reviewing their local commits and dependencies.

**No repository, branch, tag, file history, issue, release or asset was deleted or transferred as part of this inventory.**
