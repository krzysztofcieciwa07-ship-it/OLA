# OLA di-OS — decision register and current governance report

**Audit date:** 17 November 2026  
**Canonical repository:** `krzysztofcieciwa07-ship-it/OLA`  
**Audited main SHA:** `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`  
**Documentation branch:** `docs/decision-profiles-governance-20261117` (prepared from the audited main SHA)  
**Document status:** decision record and evidence snapshot; not a production certification.

## 1. Executive decision

OLA remains one canonical execution and evidence core. NINA coordinates bounded work, registered capabilities perform execution, Evidence V4 records the lifecycle, IGOR independently verifies captured evidence, and Human Gate remains a separate identity-bound decision. Codex and Gemini are development/review lanes, Jev is advisory, MetaGPT is a framework reference, and n8n is a planned trigger/connector layer. None may bypass OLA's policy, Evidence, IGOR, or Human Gate.

The latest inspected exact-main 12-hour evidence run passed on the audited main SHA. That proves the named CI/runtime flow only. It does not prove production deployment acceptance, six isolated autonomous agents, a 391-agent production system, or completed n8n/Gemini/MetaGPT integrations.

## 2. Immutable state snapshot

| Item | Observed state | Interpretation |
|---|---|---|
| Canonical `main` | `8adf30cd5e41a18a5345f66e67f5ddcdbc164862` | Current audited source identity at snapshot time |
| Main protection | GitHub branch object reports `protected=false` | Effective protection not established |
| Active ruleset | ID `25853037`, active | Contains only `deletion` and `non_fast_forward`; ref include/exclude arrays empty |
| Issue #150 | OPEN | Owner/admin verification of effective main rules remains outstanding |
| PR #253 | OPEN, DRAFT; head `4bafc831c008ab316c4b48a533c40a2b5bb7a42e` | Candidate watchdog change; not merged |
| Repository auto-delete merged branches | Disabled | Retain source branches until explicit evidence/retention review |
| Auto-merge | Disabled | No automatic merge path currently configured |

**Branch safety conclusion:** the current active ruleset blocks deletion and non-fast-forward updates, but does not establish independent pull-request approval or required status checks. Classic protection on `main` is reported false. A 403 on the detailed branch-protection endpoint means the connected integration cannot inspect all effective controls; do not interpret the inaccessible endpoint as proof that protection exists.

## 3. Evidence Gate — decision and current proof

### Required gate

A release candidate must pass the following ordered gates:

1. Exact repository, branch, full source SHA and actor identity.
2. Tenant/scope/risk policy and capability allowlist.
3. Bounded execution with input, depth, time, concurrency, output and network limits.
4. Durable run lifecycle: `run.start`, task start/completion/failure events, and exactly one terminal event.
5. Evidence V4 integrity: sequence, predecessor hash, cryptographic verification, tenant binding, writer trust and source commit.
6. Independent IGOR verification; replay verification; tamper mutation must return BLOCK.
7. Decision derived from verified evidence and policy, not from model confidence.
8. Independent Human Gate approval where required, bound to the exact evidence tip/report digest.
9. CI, source/build/image provenance and artifact digests for the exact candidate SHA.
10. Runtime health/readiness and stability window on the deployed artifact.
11. Separate deployment authorization and post-deploy verification.

Any missing, skipped, stale, mismatched, tampered or unverifiable prerequisite blocks promotion. `UNKNOWN` does not become `PASS`; `SKIPPED` does not become `PASS`; `IGOR VERIFIED` does not equal `HUMAN APPROVED`.

### Latest inspected main run

GitHub Actions run [#44162960709](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44162960709):

- workflow: `OLA 12h Autonomous Evidence Flow`;
- event: `workflow_dispatch`;
- branch: `main`;
- source SHA: `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`;
- conclusion: `success`;
- window: 2026-11-17 19:50:48–19:53:42 UTC;
- jobs: preflight PASS; focused tests PASS; NINA/real Ollama flow PASS; independent IGOR evidence PASS; final classification PASS;
- artifacts: preflight evidence, NINA/Ollama full flow, independent IGOR bundle and aggregate evidence bundle all created and not expired at the time inspected.

The workflow's own classification and Human Gate remain separate. This is a specific exact-SHA runtime/CI proof. It is not a deployed production release and does not prove unattended 24x7 liveness.

## 4. Architecture decisions

| ID | Decision | Reason / acceptance rule |
|---|---|---|
| ADR-001 | One canonical OLA core | Prevent duplicate planners, executors, evidence stores and policy gates |
| ADR-002 | NINA is the only OLA task orchestrator | Extend existing API, policy and DAG contracts rather than create parallel executor |
| ADR-003 | Evidence V4 is the canonical append-only evidence writer contract | Every source of runtime evidence must bind tenant, sequence, predecessor and cryptographic integrity |
| ADR-004 | IGOR remains independent from the orchestrator's final claim | Recompute the captured evidence; reject tamper/replay inconsistencies |
| ADR-005 | Human Gate is separate from AI/model/IGOR decisions | Require a distinct, authenticated human identity and exact digest binding |
| ADR-006 | Codex and Gemini remain engineering lanes | They can produce code/PRs, not self-approve, self-merge or deploy |
| ADR-007 | Jev/TypeSafe is advisory only | Typed model output is not verification or authorization |
| ADR-008 | MetaGPT remains a framework reference | Use its role/SOP patterns for design research; do not import a parallel executor |
| ADR-009 | n8n is an external trigger/connector layer | It calls OLA's API; it must not replace NINA, Evidence, IGOR or Human Gate |
| ADR-010 | Evidence Gateway is not a second core | Current related repository is specification-only; OLA's Evidence V4/API remain canonical |
| ADR-011 | Six current role paths are not six autonomous agents | They execute sequentially in one Python process, `execution_boundary=in_process` |
| ADR-012 | No “391 agents” claim without 391 distinct verified executions | Require unique identities, executions, cooperation/dependency graph, 391 records and independent verifier |
| ADR-013 | No deployment claim from CI success alone | Require exact image/source provenance, health and stability evidence |

## 5. Agent and service profile decisions

See [Agent Profiles](AGENT_PROFILES.md) for the full catalogue. The binding profile classification is:

| Profile | Correct role | Status |
|---|---|---|
| NINA | Orchestration and bounded planner | IMPLEMENTED; parallel DAG feature-gated |
| codeact / react / agentic_rag / mcp_tool_use / self_reflection / multi_agent | Six sequential registered role paths | IMPLEMENTED in-process; not independently isolated |
| OpenAI | External LLM provider | Adapter exists; live invocation configuration-dependent |
| Ollama | Local/allowlisted LLM provider | Adapter exists; real runtime evidenced in named CI run |
| IGOR | Independent evidence/replay verifier | IMPLEMENTED; named CI run successful |
| Human Gate | Second-identity review | Implemented for specific approval paths; not deployment permission |
| Codex | Repository coding agent | External development tool; no OLA runtime adapter |
| Gemini Agent / Agent OS | External research/coding reviewer | NOT INTEGRATED into OLA runtime |
| Jev / TypeSafe | Typed decision vector | Manual workflow; advisory only; no run found in inspected set |
| MetaGPT | Multi-agent software-team framework | External MIT reference fork; not OLA dependency or executor |
| n8n | Webhook/schedule/connectors | Service online; inspected instance had zero workflows and Python runner startup error |
| LocalAgent / Cockpit | Local device bridge and operator UI | Preview-only; owner/device identity remains not verified |
| Evidence Gateway | Evidence transport/API reference | Specification-only; no deployed service verified |

## 6. Correct agent profile facts

### OLA six role paths

- **codeact:** restricted arithmetic AST evaluator; no arbitrary shell or general Python execution.
- **react:** fixed reason/act/observe structure based on previous output; no free-running autonomous loop.
- **agentic_rag:** simple matching over up to ten recent tenant evidence rows; no vector database.
- **mcp_tool_use:** allowlisted internal SHA-256/string-length functions; not an unrestricted MCP client.
- **self_reflection:** basic prior-output heuristic; not a semantic correctness proof.
- **multi_agent:** aggregates previous in-process role outputs; not distributed agent collaboration.

Every role output records provider/model metadata where available, and model output is advisory. The action result is produced by the registered capability. The roles are sequential and carry `execution_boundary=in_process`.

### MetaGPT

The owner account has a fork at [krzysztofcieciwa07-ship-it/MetaGPT](https://github.com/krzysztofcieciwa07-ship-it/MetaGPT), whose parent is [krzys167-crypto/MetaGPT](https://github.com/krzys167-crypto/MetaGPT); the project upstream is [FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT). MetaGPT describes itself as a role-based multi-agent software-company framework, with roles such as product manager, architect, project manager and engineer, using SOP-like collaboration. The upstream README identifies an MIT license.

**Decision:** use MetaGPT as a design/reference source for specialist roles, task decomposition and SOP-based handoffs. Do not call its roles OLA agents, do not assume the fork is live, and do not route production work through it until an isolated adapter exists with strict schemas, capability/network allowlists, Evidence V4, IGOR, replay and Human Gate. Any copied/vendored MetaGPT code must retain the MIT notices and license.

## 7. Licensing decision

- OLA root `LICENSE` states the **Unlicense** public-domain dedication and provides an express warranty/liability disclaimer.
- GitHub repository metadata labels OLA `Unlicense`.
- MetaGPT is a separate MIT-licensed project; its license does not inherit OLA's Unlicense and OLA's Unlicense does not relicense MetaGPT code.
- All separately maintained third-party components and dependencies retain their own licenses.
- A complete direct/transitive dependency license audit and SBOM have not been verified in this snapshot.

**Decision:** preserve each third-party license and notice. Before redistributing the packaged product, generate an SBOM, enumerate direct and transitive licenses, review attribution/notice obligations and archive the report against the exact release SHA. Do not publish a “fully license-compliant” claim until that gate passes.

## 8. Security policy decisions

- Fail closed on malformed plans, missing evidence, unknown identity, invalid source provenance, tamper, replay mismatch, or missing approval.
- Least privilege: default GitHub Actions token read-only; elevate only job-specific scopes.
- Provider network endpoints are HTTPS/loopback or explicit allowlist only; no arbitrary outbound destinations.
- Secrets never appear in source, PR diffs, logs or artifacts; read secret names/configuration only when necessary, never value dumps.
- Agent output and advisory systems cannot authorize capabilities or promote verification.
- Tenant isolation and requester/approver separation are mandatory.
- Execution is bounded by size, depth, worker count, deadlines and output size.
- Security incident evidence is preserved before remediation; affected releases remain blocked until independently verified.
- Private vulnerability reporting must be configured before claiming production security maturity.
- Preview UI remains non-privileged and cannot perform real write/approval/deploy actions.

## 9. Branch, push, merge and close policy

### Branch and push

1. Read current `main` SHA, open PRs and applicable rules before changes.
2. Create a focused branch from exact full SHA.
3. Commit narrowly and push by fast-forward only; no force-push or rewritten shared history.
4. Re-run checks after every source change; all checks must match exact PR head SHA.
5. Do not push routine work directly to `main`.
6. Open a PR with the exact candidate SHA, risks, checks and rollback notes.

### Merge

Merge is permitted only after exact-SHA tests, security/provenance/Evidence Gate checks, independent review, resolved blocking threads, and separate Human Gate where appropriate. Squash is default for focused PRs; preserve a merge commit if a reviewed multi-commit history is necessary. After merge, record merge SHA, resulting main SHA, CI runs and deployed source identity.

### Close

- A merged PR must have an actual merge commit and a recorded resulting base SHA.
- An unmerged closed PR is explicitly classified (superseded, duplicate, rejected, abandoned, or not planned).
- Before unmerged closure, enumerate unique commits and changes not present in the base or replacement PR.
- PR closure does not delete its source branch. Branch deletion is a separate retention decision after evidence/artifact preservation.

## 10. Current open blockers

| ID | Blocker | Current state | Closure evidence |
|---|---|---|---|
| BLK-001 | Effective protection of main | NOT_VERIFIED; `main.protected=false`, ruleset 25853037 has only deletion/non-fast-forward | Owner/admin installs reviewed ruleset, verifies exact scope/status contexts, and proves missing review/checks block a test PR |
| BLK-002 | Independent reviewer | NOT_VERIFIED | A trusted independent reviewer identity and review on the exact current PR head |
| BLK-003 | n8n full pipeline | NOT CONFIGURED | Workflows imported, sandbox/network policy and credentials scoped, end-to-end OLA API test with Evidence/IGOR |
| BLK-004 | n8n Python task runner | BLOCKED in last inspected logs | External Python runner or supported container runtime; health, execution and network controls proven |
| BLK-005 | Gemini Agent runtime | NOT INTEGRATED | Adapter, typed contract, real provider run, evidence and IGOR |
| BLK-006 | Codex integration | EXTERNAL TOOL ONLY | Continue branch/PR governance; no runtime adapter is required unless chosen by architecture |
| BLK-007 | MetaGPT | REFERENCE ONLY | Isolated adapter and full acceptance contract, or retain as reference |
| BLK-008 | Evidence Gateway service | SPECIFICATION ONLY | Implement API/service, tests, image, deployment, source binding and IGOR; otherwise keep reference-only |
| BLK-009 | Six autonomous agents | NOT_VERIFIED | Separate worker/process identities, isolated contexts and independently verified communication/execution evidence |
| BLK-010 | 391-agent scale | NOT_VERIFIED | 391 unique executions, cooperation graph, evidence and independent verifier under bounded load |
| BLK-011 | Railway runtime source binding | MISMATCH IN LAST INSPECTED AUDIT | Re-read live build metadata and readiness; deployed revision must equal an accepted exact SHA |
| BLK-012 | Owner/device auth for Cockpit | NOT_VERIFIED | Persistent owner/device registry, separate credentials, revocation and authenticated action boundary |
| BLK-013 | Dependency license compliance | NOT_VERIFIED | SBOM, transitive license inventory and legal notice review per release SHA |
| BLK-014 | Private vulnerability reporting | NOT_VERIFIED | Enable and test the repository's private reporting channel |
| BLK-015 | S…X cloud execution environment | NOT_VERIFIED / DO_NOT_START | Confirm provider/project/environment/session/snapshot/repo/SHA/image/runtime/network/owner identity; then health + Evidence V4 + IGOR proof |

## S…X — cloud execution environment

**Owner reference:** `S…X`  
**Classification:** distinct cloud-execution resource; not an agent profile and not assumed to be a Sandbox product.  
**Status:** **NOT_VERIFIED / DO_NOT_START**.

### Evidence checked in this pass
- Canonical OLA repository search for `S-X`, `S X`, `SX environment` and `S-X agent environment`: no matches.
- Accessible Railway projects/environments/services: no unambiguous resource with an S…X identity.
- Connected Replit app searches for `S-X` and `SX`: no matches.
- An earlier Vercel lookup of one selected snapshot returned `snapshot_not_found`. This is a finding about that selected resource only; it does not prove that S…X is a Vercel Sandbox or that S…X is absent.

These are bounded negative searches across the connected sources, not proof that the resource does not exist in another provider, account, or workspace.

### Required resource identity before activation
Record and independently verify: provider/account/workspace, immutable project ID, environment ID, session/instance ID, snapshot ID/state, repository/worktree, branch, full source SHA, image/runtime digest, region and resource limits, network allowlist, secret custody, operator identity, health/heartbeat, and a real run ID with complete lifecycle evidence.

**Decision:** no start, resume, clone, attach, execution, publish or deploy based on the alias alone. Resolve exact immutable identifiers first; then run a bounded non-privileged health/provenance check, persist Evidence V4, and obtain independent IGOR verification. Unknown identity or provenance remains BLOCKED.

## 11. Additional governance finding

- **CODEOWNERS limitation:** the current CODEOWNERS file maps protected paths to one account only; this cannot provide independent review when that account authors the PR. The ruleset candidate has `require_code_owner_review: false`, while the security baseline describes CODEOWNERS review as a target control. Align policy and effective settings after configuring an independent reviewer.

## 12. Merge and release decision

**No merge to main and no production deployment was performed as part of this documentation update.** The documentation changes are staged on a dedicated topic branch and must be reviewed like any other repository change. The current branch policy is not strong enough to claim enforced review protection. Do not merge this PR until effective protections and an independent review are proven.

## 13. Source references

- [Canonical OLA repository](https://github.com/krzysztofcieciwa07-ship-it/OLA)
- [README](../README.md)
- [SECURITY.md](../SECURITY.md)
- [LICENSE](../LICENSE)
- [Agent runtime](../app/agent_runtime.py)
- [NINA](../app/nina.py)
- [NINA workflow planner](../app/nina_workflow.py)
- [Workflow engine](../app/workflow_engine.py)
- [IGOR workflow verifier](../app/igor_workflow.py)
- [Human Gate](../app/nina_workflow_gate.py)
- [Jev evaluation workflow](../.github/workflows/jev-evaluation.yml)
- [Main ruleset candidate](../scripts/apply_main_ruleset.py)
- [Main branch protection tracking issue #150](https://github.com/krzysztofcieciwa07-ship-it/OLA/issues/150)
- [Main evidence run #44162960709](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44162960709)
- [MetaGPT upstream](https://github.com/FoundationAgents/MetaGPT)
- [MetaGPT owner fork](https://github.com/krzysztofcieciwa07-ship-it/MetaGPT)
