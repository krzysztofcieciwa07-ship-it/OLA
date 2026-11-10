# ZBook Local Agent Runtime — Design

**Date:** 2026-11-10  
**Base revision:** `0049098994836ad7998b1226f79190f0cc2e1056`  
**Target:** Local OLA di-OS runtime on the ZBook  
**Status:** User-approved design; specialist-agent catalogue clarified on 2026-11-10. Implementation has not started.

## 1. Goal and claim boundary

Deliver a local, repeatable six-agent execution path on the ZBook, using local Ollama, an append-only local evidence ledger, and an independent IGOR verifier. AURORA must operate against this local runtime and expose real run state and evidence.

The first milestone proves **six distinct worker executions**, not 391 agents, production-scale autonomy, or production readiness. No result is labelled autonomous/verified unless the evidence proves the required execution boundary, real model invocation, capability use, lifecycle completion, and independent verification.

The current `app/agent_runtime.py` records `execution_boundary=in_process`. The current workstation harness forces `OLA_LLM_MODE=deterministic`. Those paths remain valid deterministic tests, but they cannot satisfy this milestone's real-agent claim.

## 2. Architecture

```text
ZBook (local-only)
├── AURORA UI + OLA API (127.0.0.1 only)
├── Trusted local supervisor
│   ├── NINA policy / task scheduler
│   ├── six one-shot worker containers
│   │   ├── codeact
│   │   ├── react
│   │   ├── agentic_rag
│   │   ├── mcp_tool_use
│   │   ├── self_reflection
│   │   └── multi_agent
│   ├── Ollama provider gateway (real invocation; fail closed)
│   └── Evidence Ledger writer
├── Local Ollama endpoint (allowlisted)
└── IGOR verifier (separate process/container; read-only evidence)
```

The supervisor is the trusted control plane. It launches a fresh, short-lived container for each agent execution using a pinned worker image. Worker containers receive no Docker socket, no production credentials, no direct database access, no writable host mounts, and no unrestricted network access. Their only permitted communication is the structured request/response channel to the supervisor. The supervisor is the only component allowed to call Ollama and write evidence.

The supervisor itself runs as the local user, exposes the API only on loopback, accepts only validated task contracts, and launches only the fixed, pinned worker image and fixed entrypoint. No user-supplied shell command, image, executable path, or arbitrary tool name is accepted.

This is a container/process isolation boundary, not a claim of a formally verified sandbox or protection against a compromised host administrator.

## 3. Agent execution contract

Each execution must carry:

- stable role identifier and fresh `agent_instance_id`;
- fresh `run_id` and unique worker container/process identity;
- tenant and task identifiers;
- input and context SHA-256 digests;
- explicit capability allowlist;
- provider, exact model name, invocation type, request/response identifiers, and prompt/output digests;
- worker image digest and exact source commit;
- start/end timestamps, exit code, bounded stdout/stderr metadata, and final status.

The six roles are the existing registered roles: `codeact`, `react`, `agentic_rag`, `mcp_tool_use`, `self_reflection`, and `multi_agent`. Role names alone do not establish six agents. Each role must run in its own one-shot container with a distinct runtime identity.

Worker input and output use versioned JSON contracts with strict schemas, bounded payload sizes, explicit timeouts, and rejection of unknown fields. Handoffs between agents are explicit envelopes containing source role, destination role, run ID, dependency IDs, and content digest. No shared mutable context or direct worker-to-worker filesystem access is permitted.

## 4. Model and capability boundaries

- The local provider is Ollama. The selected model must be explicitly configured and confirmed present during preflight; the implementation must not silently choose an unverified model.
- Real mode requires `OLA_LLM_PROVIDER=ollama` and `OLA_LLM_MODE=required`. Missing Ollama, missing model, timeout, malformed output, or schema failure blocks the run. There is no deterministic fallback in a real run.
- Planner and worker outputs are constrained to JSON schemas. The planner's proposed tools and dependencies are validated independently before execution.
- Model output is advisory. Only registered capabilities produce action results.
- The initial capability set is limited to existing safe OLA capabilities and read-only, tenant-scoped evidence retrieval. No arbitrary shell, unrestricted Python, arbitrary URL fetch, external side effect, or production mutation is exposed.
- Network egress is deny-by-default. The supervisor's Ollama route is the only model endpoint allowlisted for the local run. Worker containers have no general internet access.
- Secrets are not passed to workers or included in evidence. Logs redact credentials and cap output size.

The provider adapter remains separate from OpenAI integration. OpenAI may remain available for separately configured cloud/test environments, but the ZBook acceptance run is explicitly local Ollama and cannot silently fall back to OpenAI.

## 5. Evidence lifecycle and IGOR

The supervisor is the sole Evidence Ledger writer. The local ledger preserves the existing append-only/hash-chain guarantees and records, at minimum:

`run.start → agent.start → model.request → model.response → capability.start → capability.end → agent.end → agent.handoff (when used) → run.end`

Each record binds the run, agent instance, process/container identity, source commit, model/provider, capability, input/output digests, predecessor hash, and result. A failed or interrupted run must end with an explicit failed/blocked lifecycle record where the supervisor is still able to write it; incomplete runs must never be reported as verified.

IGOR runs separately from the supervisor and runtime implementation. It receives read-only evidence and independently recomputes the complete hash chain and run contract. It must reject missing or duplicate agent identities, missing lifecycle events, wrong process boundaries, deterministic invocation in a real run, wrong provider/model, invalid JSON contracts, missing capability evidence, incomplete handoffs, source/image mismatch, tenant mismatch, and any tampering. The verifier must not import the runtime's evidence-writing or verification implementation.

## 6. AURORA and API integration

AURORA is served from the same local origin as the local API to avoid cross-origin/private-network browser access problems. It must display actual readiness, active run state, each agent's status, provider/model, evidence availability, verifier result, and blocked reason.

The UI/API contract must be checked against the real OpenAPI schema and exercised end to end. The existing approval flow must include `decision_report.report_sha256` in the approval request; `tip_hash` alone is insufficient for the backend gate. UI presence of a route is not evidence that the route returns verified data.

Required checks include liveness `/health`, readiness `/readyz`, run creation/status, approval rejection and success paths, evidence retrieval, audit output, and IGOR verification. Readiness is false unless Ollama/model, ledger, worker image, and verifier prerequisites are available.

## 7. Workstation lifecycle and operational safety

The Windows/PowerShell workstation kit is the starting point, subject to preflight confirmation of the actual ZBook OS and installed dependencies. The launcher must:

1. inspect OS, Python, Docker Engine, disk/RAM availability, Ollama reachability, and installed model names;
2. pin the exact source commit and worker image digest;
3. refuse to overwrite an existing work directory or evidence run;
4. start only loopback-bound services;
5. run the six-agent smoke task and independent IGOR verification;
6. perform a tamper-negative test and confirm that IGOR returns BLOCK;
7. write a manifest with source, image, model, run ID, gate results, and SHA-256 checksums;
8. stop services cleanly and preserve evidence.

Start/stop/status/verify operations must be idempotent. A failed prerequisite or failed gate stops the launch and reports a precise BLOCKED reason. Railway, Stripe, customer tenants, and production services are outside this local execution path and must not be mutated by it.

## 8. Acceptance criteria

The milestone is accepted only when all of the following are demonstrated on the ZBook:

1. AURORA and API are reachable only on loopback and `/readyz` reports the actual dependency state.
2. One real task produces six distinct one-shot worker containers/process identities, one for each registered role.
3. Every agent has a real Ollama invocation attributed to its execution identity; deterministic mode and silent provider fallback are rejected.
4. The final result is produced by registered capabilities, not merely copied from model text.
5. The ledger contains a complete, correctly ordered lifecycle and hash chain for the run.
6. IGOR, in a separate process/container and using read-only evidence, returns VERIFIED for the valid run.
7. A tampered or incomplete copy of the same evidence returns BLOCK.
8. AURORA displays the same run ID, statuses, evidence, and verifier outcome returned by the API.
9. Automated tests cover success, timeout, worker crash, malformed JSON, duplicate identity, forbidden capability, network denial, cross-tenant access, interrupted run, restart recovery, approval hash mismatch, and tampering.
10. The workstation manifest binds the result to the exact source commit, worker image digest, Ollama model, and evidence checksums.

A single successful smoke run does not establish a 60-minute stability window, 391-agent cooperation, production-scale resilience, or production readiness. Those remain separate evidence gates.

## 9. Implementation sequence

1. Reconcile the worker contract and verifier with the existing runtime and evidence schema; add failing tests first.
2. Implement the supervisor-to-one-shot-worker boundary and strict JSON protocol.
3. Implement the Ollama gateway with required mode, structured output, bounded timeouts, and no fallback.
4. Implement supervisor-owned lifecycle evidence and the independent IGOR verifier.
5. Integrate AURORA and repair the approval payload contract.
6. Harden the ZBook start/stop/preflight/verification scripts.
7. Run targeted tests, full tests, real Ollama smoke test, fault-injection tests, tamper test, and workstation acceptance run.

## 10. Explicit exclusions

This milestone does not implement 391 concurrent agents, a public multi-tenant service, automatic production remediation, a new billing flow, or a claim that the ZBook has been configured. Those require separate designs and evidence. No Railway deployment or production secret change is part of this work.


## 11. Full OLA specialist-agent catalogue

The six worker roles in Sections 2–3 are **execution patterns**, not the complete list of OLA specialist agents. OLA must support specialist agents as registered configurations that use the common execution fabric, evidence lifecycle, NINA policy, and IGOR verification.

The initial specialist catalogue preserves the previously defined OLA roles:

| Specialist | Responsibility | Initial execution profiles | Security boundary |
|---|---|---|---|
| **Hermes** | General operator; carries out approved user tasks and coordinates tool use. | `react`, `mcp_tool_use` | No authority outside the requester's granted capabilities; external side effects require Human Gate. |
| **Builder** | Builds and modifies code and application components. | `codeact`, `mcp_tool_use` | Repository/workspace-scoped changes; no production deployment or secret mutation without approval. |
| **Scout** | Finds information, sources, and relevant internal/external evidence. | `agentic_rag`, `mcp_tool_use` | Read-only retrieval; external access only through explicit domain allowlists. |
| **Guardian** | Reviews security, policy, compliance, and unsafe execution paths. | `self_reflection`, `agentic_rag` | Read-only reviewer; cannot approve its own changes or replace IGOR. |
| **Archivist** | Maintains project chronicle, memory, and structured knowledge. | `agentic_rag`, `mcp_tool_use` | Writes only through the designated memory/chronicle API; cannot edit or delete evidence-ledger history. |
| **Researcher** | Performs structured research, synthesis, and source-backed analysis. | `agentic_rag`, `react`, `mcp_tool_use` | Source provenance required; unsupported claims remain UNKNOWN. |
| **Tester** | Designs and runs bounded tests and validation scenarios. | `codeact`, `mcp_tool_use` | Test commands and fixtures are allowlisted; no production data mutation. |
| **DevOps** | Diagnoses runtime, deployment, infrastructure, and reliability issues. | `react`, `mcp_tool_use` | Read-only by default; production changes require Human Gate and a separately scoped credential. |
| **Sales** | Researches prospects, prepares account intelligence, and drafts sales materials. | `agentic_rag`, `react`, `mcp_tool_use` | May prepare drafts; sending messages, changing CRM state, or making commercial commitments requires approval. |
| **Finance** | Analyzes revenue, costs, billing evidence, and financial reporting. | `agentic_rag`, `react`, `mcp_tool_use` | Read-only financial analysis by default; no money movement, refunds, payment changes, or financial commitments. |

Two additional platform roles are part of the original OLA design but are **control-plane services**, not ordinary task workers:

- **Orchestrator / NINA:** decomposes work, schedules specialist agents, validates dependencies, enforces tenant and capability policy, and collects outcomes. It cannot self-certify completion or bypass IGOR/Human Gate.
- **Broker:** chooses among explicitly configured model providers according to policy (privacy, capability, latency, cost, and quality constraints). It cannot add providers, expand network allowlists, or override the run's required provider. For the ZBook acceptance run, Ollama remains mandatory.

The registry must represent the specialist identity separately from the execution pattern. A versioned `AgentSpec` should bind at least `agent_id`, `specialist_role`, `execution_profile`, `capability_allowlist`, `memory_namespace`, `provider_policy`, `resource_limits`, `approval_policy`, and `status`. A role is not available merely because a row exists: its required capabilities, policy tests, and evidence/verifier contract must pass before its status can become `AVAILABLE`.

## 12. Agent instances, 391 target, and rollout

The 391 target means **391 uniquely identified, scheduled agent instances/executions with verifiable work and cooperation evidence**. It does not mean 391 different specialist types or 391 model processes permanently resident on the ZBook.

The existing `app/agent_registry.py` currently creates IDs such as `agent-001` and assigns the same generated string as the `role`. The existing `tests/test_391_agent_runtime.py` checks uniqueness of those generated role strings, while `run_multi_agent_task` reports `execution_mode=digest_only_simulation` and `cooperation_verified=false`. This is registry scaffolding and a labelled simulation, not proof of 391 real cooperating agents. The registry must be corrected so that IDs are unique while specialist roles come from the finite catalogue and may repeat.

The rollout is staged:

1. **Foundation:** prove six isolated execution profiles, real local Ollama calls, supervisor-owned evidence, and independent IGOR verification.
2. **Specialists:** register the ten task-specialist roles above with explicit permissions, memory namespaces, provider policies, and tests. Enable each role only after its capabilities and evidence path pass.
3. **Control plane:** connect Orchestrator/NINA and Broker to the specialist registry, bounded scheduler, policy gate, and human approval path.
4. **Teams:** prove real handoffs, dependency edges, partial failure handling, retries, and recovery across specialist roles.
5. **391-instance proof:** schedule 391 unique instance identities over the finite specialist catalogue, using bounded concurrency and queueing appropriate to measured ZBook resources. Each counted instance must have a real execution identity and its own evidence; a digest-only row, role label, UUID, or synthetic edge is insufficient.

A 391-instance acceptance run must prove 391 unique agent IDs, 391 distinct execution/process identities, actual task execution, real provider provenance where LLM reasoning is claimed, capability outcomes, communication/dependency edges, complete lifecycle evidence, a valid hash chain, and independent IGOR verification. IGOR must reject duplicate IDs, duplicate process identities, missing runs, fabricated edges, incomplete lifecycle, tampering, and results without the required capability evidence.

The initial six-worker milestone does not mark all ten specialists AVAILABLE and does not claim the 391 target is complete. It creates the execution substrate on which the specialist catalogue and 391-instance rollout can be built without duplicating runtimes or weakening policy.
