# OLA Full Agent Ecosystem Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ZBook-local OLA execution fabric for the complete specialist-agent catalogue, prove six isolated worker execution profiles with real Ollama inference and independent IGOR verification, then validate 391 uniquely identified cooperating instances under measured resource limits.

**Architecture:** NINA/Orchestrator and Broker form the trusted control plane. Ten specialist agents are registered as policy-bound definitions that execute through six generic worker profiles; a supervisor launches one-shot isolated workers, brokers Ollama calls, and alone writes the append-only ledger. IGOR independently verifies run evidence, while AURORA presents the real local runtime state.

**Tech Stack:** Python 3.13, FastAPI, Pydantic (via FastAPI dependency), Docker Engine, local Ollama, SQLite append-only evidence ledger, pytest, PowerShell workstation launcher, GitHub Actions.

**Specification:** `docs/specs/2026-11-10-zbook-local-agent-runtime-design.md`

## Global Constraints

- The ten specialist roles are Hermes, Builder, Scout, Guardian, Archivist, Researcher, Tester, DevOps, Sales, and Finance.
- Orchestrator/NINA and Broker are control-plane services; they cannot bypass policy, IGOR, or Human Gate.
- The six existing names `codeact`, `react`, `agentic_rag`, `mcp_tool_use`, `self_reflection`, and `multi_agent` are execution profiles, not the full specialist catalogue.
- Every counted execution needs a unique stable agent ID, a unique run-scoped instance ID, and a distinct worker process/container identity.
- The worker must not receive the Docker socket, production credentials, direct ledger access, unrestricted network access, or arbitrary shell commands.
- The supervisor is the sole Ollama gateway and evidence writer. Model requests/responses are bound to the exact specialist and execution identity.
- The ZBook acceptance run requires Ollama and a pinned installed model. Missing model, malformed JSON, timeout, or provider failure blocks; no deterministic or OpenAI fallback is permitted.
- The model proposes; registered capabilities produce action results. Model text alone is never accepted as a tool outcome.
- The independent verifier must not import the runtime's evidence-writing or verification implementation.
- The existing hash-chain and append-only guarantees, tenant isolation, source provenance, and Human Gate remain intact.
- 391 instances means 391 actual scheduled executions with verifiable work and cooperation evidence; it does not mean 391 unique specialist types or 391 permanently resident model processes.
- A digest-only simulation, UUID list, role label, or generated graph is not evidence of 391 cooperating agents.
- No Railway, Stripe, production tenant, or production secret mutation is part of the ZBook-local rollout.

---

### Task 1: Specialist catalogue and typed agent registry

**Files:**
- Create: `app/agent_catalog.py` (proposed)
- Modify: `app/agent_registry.py`
- Modify: `app/main.py`
- Test: `tests/test_agent_registry.py` (proposed)
- Modify: `tests/test_391_agent_runtime.py`

**Observed starting point:** `app/agent_registry.py` currently creates `Agent(agent_id="agent-001", role="agent-001")`; `app/main.py` calls `build_agent_registry(391)` at import time. The 391 test currently requires 391 unique generated role strings. That proves neither specialist identity nor real execution.

**Interfaces:**
- `load_agent_catalog() -> dict[str, AgentDefinition]`
- `build_agent_registry(manifest: Sequence[AgentInstanceSpec]) -> list[AgentInstanceSpec]`
- `AgentDefinition` binds specialist role, description, execution profiles, capability allowlist, memory namespace, provider policy, resource limits, approval policy, and availability status.
- `AgentInstanceSpec` binds unique `agent_id` to a registered specialist role and an explicit instance configuration.

**Specialist definitions:** Hermes, Builder, Scout, Guardian, Archivist, Researcher, Tester, DevOps, Sales, Finance. Orchestrator/NINA and Broker remain control-plane services rather than normal task-worker definitions.

- [ ] **Step 1: Add failing registry tests**
  - Assert the catalogue contains exactly the ten specialist roles and the two separately classified control-plane services.
  - Assert every specialist has at least one supported execution profile and an explicit capability/approval policy.
  - Assert duplicate `agent_id` values and unknown specialist roles are rejected.
  - Assert multiple instances may share a specialist role while retaining unique `agent_id` values.
  - Assert the 391 fixture has 391 unique IDs but roles drawn from the finite specialist catalogue; role names are not required to be unique.
  - Assert importing `app.main` does not create a fabricated 391-agent registry as a side effect.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_agent_registry.py tests/test_391_agent_runtime.py`
  - Expected: failure because the current registry equates generated IDs with roles and does not expose specialist definitions.

- [ ] **Step 3: Implement the typed catalogue and registry**
  - Define immutable specialist and instance contracts.
  - Keep the ten role definitions separate from the six execution profiles.
  - Replace count-only identity generation with explicit manifest-backed instance registration.
  - Remove import-time generation of 391 synthetic IDs from `app/main.py`; route authorization must use the actual registered definition and policy, not a generated ID list.
  - Keep any synthetic 391 manifest clearly labelled as a test fixture.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_agent_registry.py tests/test_391_agent_runtime.py`
  - Expected: all registry tests pass; role repetition is valid, ID duplication and unknown roles are rejected.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_agent_runtime.py tests/test_nina_workflow.py tests/test_nina_workflow_api.py`
  - Expected: existing six-profile deterministic behavior remains explicitly labelled deterministic/in-process until Task 2 is complete.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add app/agent_catalog.py app/agent_registry.py app/main.py tests/test_agent_registry.py tests/test_391_agent_runtime.py`
  - `git commit -m "feat: add typed OLA specialist agent registry"`

### Task 2: One-shot isolated worker protocol and supervisor

**Files:**
- Create: `app/agent_protocol.py` (proposed)
- Create: `app/agent_worker.py`
- Create: `app/agent_supervisor.py` (proposed)
- Create: `workstation/worker.Dockerfile` (proposed)
- Modify: `app/agent_runtime.py`
- Test: `tests/test_agent_worker_runtime.py` (proposed)
- Test: `tests/test_agent_supervisor.py` (proposed)

**Interfaces:**
- `run_agent_worker(agent_instance_id: str, profile: str, request: AgentWorkerRequest) -> AgentWorkerResult`
- `AgentWorkerRequest` and `AgentWorkerResult` are versioned strict JSON contracts.
- `AgentSupervisor.execute(instance: AgentInstanceSpec, request: AgentTaskRequest) -> AgentExecution`

- [ ] **Step 1: Add failing worker-boundary tests**
  - Assert every execution gets a fresh worker process/container identity.
  - Assert a worker receives only the fixed image, fixed entrypoint, validated JSON, and its scoped capabilities.
  - Assert the launch command does not include a Docker socket, host home mount, production secret, or arbitrary shell command.
  - Assert worker containers use read-only root filesystem, no network, dropped Linux capabilities, no-new-privileges, bounded CPU/memory/PIDs, and a bounded wall-clock timeout.
  - Assert malformed JSON, unknown fields, oversized input/output, nonzero worker exit, timeout, and worker crash return BLOCK/FAILED without a VERIFIED terminal result.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_agent_worker_runtime.py tests/test_agent_supervisor.py`
  - Expected: failure because `app/agent_worker.py` and the supervisor boundary do not exist.

- [ ] **Step 3: Implement the minimum worker boundary**
  - Use a fixed, pinned worker image and fixed entrypoint; never interpolate user input into a shell command.
  - Exchange one request and one response through bounded stdin/stdout JSON.
  - Run each worker as a fresh one-shot container; do not share mutable worker state.
  - Keep the Ollama gateway and ledger writer in the supervisor; workers receive only the model result and approved capability envelope.
  - Attribute each model request/response to the exact worker instance and specialist role.
  - Fail closed if Docker isolation flags or the pinned image digest cannot be confirmed.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_agent_worker_runtime.py tests/test_agent_supervisor.py`
  - Expected: success, with each test proving a separate process/container boundary and bounded failure semantics.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_agent_runtime.py tests/test_agent_registry.py`
  - Expected: legacy deterministic tests remain separate from the new isolated-worker proof.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add app/agent_protocol.py app/agent_worker.py app/agent_supervisor.py workstation/worker.Dockerfile app/agent_runtime.py tests/test_agent_worker_runtime.py tests/test_agent_supervisor.py`
  - `git commit -m "feat: add isolated OLA agent worker supervisor"`

### Task 3: Provider adapters and strict structured model output

**Files:**
- Create: `app/llm_providers/__init__.py` (proposed)
- Create: `app/llm_providers/base.py` (proposed)
- Create: `app/llm_providers/ollama.py` (proposed)
- Create: `app/llm_providers/openai.py` (proposed)
- Create: `app/agent_contracts.py` (proposed)
- Modify: `app/agent_runtime.py`
- Test: `tests/test_llm_provider_contract.py` (proposed)
- Test: `tests/test_ollama_agent_runtime.py` (proposed)

**Interfaces:**
- `LLMProvider.generate_json(request: ModelRequest, response_schema: dict) -> ModelResponse`
- `OllamaProvider` implements the local ZBook provider.
- `OpenAIProvider` remains an isolated provider adapter for separately configured cloud/test use.
- Each `ModelResponse` carries provider, exact model, response ID, invocation type, prompt digest, output digest, and validated structured output.

- [ ] **Step 1: Add failing provider tests**
  - Assert `OLA_LLM_PROVIDER=ollama` and `OLA_LLM_MODE=required` are mandatory for the ZBook profile.
  - Assert a missing Ollama endpoint/model, HTTP failure, timeout, malformed JSON, schema violation, or missing response identity blocks the run.
  - Assert there is no fallback to deterministic mode or OpenAI when Ollama fails.
  - Assert OpenAI and Ollama adapters cannot read or mutate each other's credentials/configuration.
  - Assert planner/worker structured output rejects extra fields and invalid capability names.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_llm_provider_contract.py tests/test_ollama_agent_runtime.py`
  - Expected: failure because provider selection and response handling currently live in one private function and can fall back to the deterministic model.

- [ ] **Step 3: Implement provider separation**
  - Move provider-specific HTTP and response parsing into separate adapters.
  - Keep provider selection explicit and immutable for each run.
  - Require strict structured JSON output validated against the task/agent schema before a capability can run.
  - Enforce endpoint allowlists, bounded timeouts, token limits, and secret redaction.
  - Record model invocation provenance without storing raw credentials or unnecessary prompt contents.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_llm_provider_contract.py tests/test_ollama_agent_runtime.py`
  - Expected: Ollama success cases pass; all missing/invalid/fallback cases are BLOCKED.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_agent_runtime.py tests/test_nina_workflow.py tests/test_ollama_igor_evidence_contract.py`
  - Expected: existing deterministic CI tests still pass only in their explicitly labelled test profile; ZBook profile never silently degrades.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add app/llm_providers app/agent_contracts.py app/agent_runtime.py tests/test_llm_provider_contract.py tests/test_ollama_agent_runtime.py`
  - `git commit -m "feat: isolate Ollama and OpenAI structured providers"`

### Task 4: Lifecycle evidence and independent local IGOR verifier

**Files:**
- Modify: `app/agent_supervisor.py`
- Modify: `app/agent_runtime.py`
- Create: `scripts/verify_local_agent_runtime.py` (proposed)
- Test: `tests/test_agent_lifecycle_evidence.py` (proposed)
- Test: `tests/test_local_igor_verifier.py` (proposed)
- Modify: `tests/test_independent_verifier_tamper.py`

**Interfaces:**
- Supervisor emits `run.start`, `agent.start`, `model.request`, `model.response`, `capability.start`, `capability.end`, `agent.end`, optional `agent.handoff`, and `run.end`.
- `verify_local_agent_run(evidence_path, expected_run, expected_commit, expected_model) -> VerificationResult` is standalone and read-only.

- [ ] **Step 1: Add failing lifecycle/verifier tests**
  - Assert exactly one run start and one terminal run end.
  - Assert each worker has a unique agent ID, instance ID, process/container identity, source commit, image digest, provider/model, capability, and input/output digests.
  - Assert every start has a terminal end or explicit failure record.
  - Assert missing, reordered, duplicated, cross-tenant, deterministic, wrong-provider, wrong-model, wrong-image, and incomplete handoff evidence is rejected.
  - Assert a valid run verifies and a mutated copy of the same ledger returns BLOCK.
  - Assert verifier source imports no application runtime or evidence-writer module.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_agent_lifecycle_evidence.py tests/test_local_igor_verifier.py tests/test_independent_verifier_tamper.py`
  - Expected: failure because current evidence uses `execution_boundary=in_process` and the standalone verifier explicitly expects that boundary.

- [ ] **Step 3: Implement supervisor-owned evidence**
  - Keep the supervisor as the only writer to the local append-only ledger.
  - Bind every event to the source commit, worker image digest, model response identity, agent instance, process/container identity, and capability outcome.
  - Make finalization idempotent and record failed/interrupted runs without promoting them to VERIFIED.
  - Implement IGOR as an independent read-only verifier with its own hash and lifecycle checks.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_agent_lifecycle_evidence.py tests/test_local_igor_verifier.py tests/test_independent_verifier_tamper.py`
  - Expected: valid evidence is VERIFIED; tampered or incomplete evidence is BLOCK.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_agent_runtime.py tests/test_igor_workflow.py tests/test_evidence_concurrency.py`
  - Expected: existing ledger, tenant isolation, and hash-chain tests remain green.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add app/agent_supervisor.py app/agent_runtime.py scripts/verify_local_agent_runtime.py tests/test_agent_lifecycle_evidence.py tests/test_local_igor_verifier.py tests/test_independent_verifier_tamper.py`
  - `git commit -m "feat: add independent local agent evidence verification"`

### Task 5: NINA/Orchestrator, Broker, specialist policies, and real handoffs

**Files:**
- Modify: `app/nina.py`
- Modify: `app/nina_workflow.py`
- Modify: `app/workflow_engine.py`
- Create: `app/agent_policy.py` (proposed)
- Create: `app/model_broker.py` (proposed)
- Test: `tests/test_specialist_agent_policies.py` (proposed)
- Test: `tests/test_agent_handoffs.py` (proposed)
- Modify: `tests/test_nina_workflow.py`

**Interfaces:**
- `NinaOrchestrator.plan(task, specialist_specs) -> AgentPlan`
- `ModelBroker.select_provider(agent_spec, run_policy) -> ProviderDecision`
- `AgentHandoff(source_agent_id, target_agent_id, run_id, dependency_ids, payload_digest)`

- [ ] **Step 1: Add failing policy and handoff tests**
  - Assert each of the ten specialists receives only its registered capabilities.
  - Assert Guardian is read-only and cannot approve its own findings.
  - Assert Builder cannot deploy or change secrets; DevOps cannot mutate production without Human Gate.
  - Assert Sales cannot send communications or make commitments without approval.
  - Assert Finance cannot move money, refund, or change payment state.
  - Assert Archivist cannot modify/delete evidence-ledger records.
  - Assert Broker selects only providers allowed by the run policy and cannot override the ZBook's Ollama-only policy.
  - Assert NINA rejects unknown specialist roles, missing dependencies, dependency cycles, and unauthorized capability escalation.
  - Assert handoffs are linked by digest and recorded in evidence; failed upstream work blocks dependent nodes.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_specialist_agent_policies.py tests/test_agent_handoffs.py tests/test_nina_workflow.py`
  - Expected: failure because the current NINA registry exposes only three generic tools and does not route specialist definitions.

- [ ] **Step 3: Implement policy-bound orchestration**
  - Keep NINA as the scheduling/policy control plane.
  - Implement Broker as a provider-selection policy service, not an unconstrained autonomous agent.
  - Execute specialist definitions through the six common profiles and the supervisor boundary.
  - Add explicit task dependencies, handoff envelopes, bounded concurrency, and terminal status propagation.
  - Keep Guardian/IGOR review independent; no agent may self-approve.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_specialist_agent_policies.py tests/test_agent_handoffs.py tests/test_nina_workflow.py`
  - Expected: all role-boundary, policy, and handoff tests pass.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_nina_workflow_api.py tests/test_nina_run_approval_gate.py tests/test_igor_workflow.py`
  - Expected: API, Human Gate, and independent verification paths remain correct.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add app/nina.py app/nina_workflow.py app/workflow_engine.py app/agent_policy.py app/model_broker.py tests/test_specialist_agent_policies.py tests/test_agent_handoffs.py tests/test_nina_workflow.py`
  - `git commit -m "feat: orchestrate OLA specialist agents with policy gates"`

### Task 6: AURORA local UI and API contract

**Files:**
- Create: `web/aurora.html` (proposed integration target for the supplied `ui-before-local-executor.html`)
- Modify: `app/main.py`
- Test: `tests/test_aurora_local_api_contract.py` (proposed)
- Test: `tests/test_nina_run_approval_gate.py`

**Interfaces:**
- AURORA uses same-origin local API routes for readiness, run start/status, evidence, audit, and approval.
- Approval request includes `tenant_id`, `approver_id`, `run_id`, `tip_hash`, `report_sha256`, and reason as required by the backend gate.

- [ ] **Step 1: Add failing API/UI contract tests**
  - Assert UI route paths and request fields match FastAPI OpenAPI.
  - Assert approval payload contains `decision_report.report_sha256` value and rejects missing/mismatched report hash.
  - Assert UI shows actual `/readyz` state, run ID, per-agent status, provider/model, evidence status, IGOR result, and precise blocked reason.
  - Assert UI cannot call an arbitrary host, URL, shell, or capability.
  - Assert liveness `/health` is not treated as readiness.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_aurora_local_api_contract.py tests/test_nina_run_approval_gate.py`
  - Expected: failure because the supplied AURORA UI omits the required `report_sha256` field and the current repository dashboard is not the uploaded AURORA surface.

- [ ] **Step 3: Implement same-origin AURORA integration**
  - Integrate the supplied UI into the repository at `web/aurora.html`.
  - Serve it from the local API origin.
  - Wire readiness, run state, evidence, audit, approval, and IGOR status to real API responses.
  - Display UNKNOWN/BLOCKED distinctly; never infer success from route existence or a successful health ping.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_aurora_local_api_contract.py tests/test_nina_run_approval_gate.py`
  - Expected: API payloads and UI route contracts match; missing report digest is rejected.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_nina_workflow_api.py tests/test_nina_run_approval_gate.py tests/test_igor_workflow.py`
  - Expected: all same-origin API and approval paths pass.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add web/aurora.html app/main.py tests/test_aurora_local_api_contract.py tests/test_nina_run_approval_gate.py`
  - `git commit -m "feat: connect AURORA to local OLA runtime"`

### Task 7: ZBook preflight, lifecycle launcher, and acceptance manifest

**Files:**
- Modify: `workstation/OLA-Workstation.ps1`
- Modify: `workstation/README.md`
- Create: `workstation/OLA-Local-Runtime.ps1` (proposed)
- Test: `tests/test_workstation_contract.py` (proposed)
- Create: `scripts/verify_workstation_manifest.py` (proposed)

- [ ] **Step 1: Add failing workstation contract tests**
  - Assert the launcher pins source commit and worker image digest.
  - Assert preflight checks OS, Docker Engine, Python, available disk/RAM, Ollama reachability, and installed model name.
  - Assert start/stop/status/verify are idempotent and bind API ports to loopback.
  - Assert no production secrets are requested or mounted.
  - Assert the old deterministic-only harness cannot emit a real-agent READY manifest.
  - Assert the manifest includes run ID, source SHA, image digest, model, all gate outcomes, and SHA-256 checksums.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_workstation_contract.py`
  - Expected: failure because the current workstation script hardcodes `OLA_LLM_MODE=deterministic` and only checks `/health`.

- [ ] **Step 3: Implement the workstation lifecycle**
  - Separate deterministic CI verification from the real Ollama ZBook acceptance profile.
  - Add preflight and fail-closed dependency checks.
  - Add idempotent start, stop, status, and verify actions.
  - Keep API bound to loopback and preserve evidence after shutdown.
  - Do not assume Windows until preflight confirms the ZBook operating system.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_workstation_contract.py`
  - Expected: all workstation contract tests pass and deterministic-only configuration cannot claim READY.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -q tests/test_agent_worker_runtime.py tests/test_local_igor_verifier.py tests/test_workstation_contract.py`
  - Expected: launcher, worker, and verifier contracts agree on the same run manifest.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add workstation/OLA-Workstation.ps1 workstation/README.md workstation/OLA-Local-Runtime.ps1 tests/test_workstation_contract.py scripts/verify_workstation_manifest.py`
  - `git commit -m "feat: add hardened ZBook local runtime launcher"`

### Task 8: 391-instance cooperation proof and bounded load validation

**Files:**
- Modify: `app/agent_registry.py`
- Modify: `app/agent_runtime.py`
- Create: `scripts/verify_391_agent_runtime.py` (proposed)
- Create: `scripts/run_391_agent_validation.py` (proposed)
- Test: `tests/test_391_agent_runtime.py`
- Test: `tests/test_independent_391_verifier.py` (proposed)
- Test: `tests/test_production_scale_gate.py` (proposed)
- Modify: `.github/workflows/e2e.yml`

- [ ] **Step 1: Add failing 391 proof tests**
  - Assert 391 unique agent IDs, 391 unique run-scoped instance IDs, and 391 unique worker process/container identities.
  - Assert specialist roles are drawn from the ten-role catalogue and may repeat.
  - Assert each counted instance has a real start/end lifecycle, capability result, and evidence record.
  - Assert each dependency/handoff edge references existing source/target executions and matching payload digests.
  - Assert duplicate, missing, fabricated, cyclic, or tampered edges are rejected.
  - Assert the verifier rejects digest-only simulations and returns `SIMULATED` or `BLOCK`, never `VERIFIED`.
  - Assert concurrency is bounded by the measured workstation policy; a 391-entry manifest does not imply 391 concurrent containers.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -q tests/test_391_agent_runtime.py tests/test_independent_391_verifier.py tests/test_production_scale_gate.py`
  - Expected: failure because the current registry uses synthetic role labels and `run_multi_agent_task` reports `digest_only_simulation`.

- [ ] **Step 3: Implement real bounded scheduling and independent proof**
  - Schedule manifest-defined instances through the specialist registry and isolated worker supervisor.
  - Persist explicit dependency and handoff records.
  - Add independent verification of identities, process boundaries, actual task results, provider provenance, lifecycle, and full evidence graph.
  - Keep the test fixture and real hardware acceptance result in separate evidence classes.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -q tests/test_391_agent_runtime.py tests/test_independent_391_verifier.py tests/test_production_scale_gate.py`
  - Expected: controlled tests prove the verifier rejects simulations and incomplete runs; a real 391-run is not marked VERIFIED until it executes on the target workstation.

- [ ] **Step 5: Run full repository checks**
  - Run: `python -m pytest -q`
  - Expected: full suite passes without weakening existing assertions.
  - Run: `docker build --tag ola-local-candidate .`
  - Expected: deployment image builds with the pinned worker image and runtime contract.
  - Run the real ZBook acceptance launcher only after target-machine preflight and Ollama model confirmation.
  - Expected: manifest reports each gate separately; overall READY only when every required local gate and IGOR check passes.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add app/agent_registry.py app/agent_runtime.py scripts/verify_391_agent_runtime.py scripts/run_391_agent_validation.py tests/test_391_agent_runtime.py tests/test_independent_391_verifier.py tests/test_production_scale_gate.py .github/workflows/e2e.yml`
  - `git commit -m "feat: prove bounded 391-agent cooperation"`

## Unresolved operational decisions

These do not block implementation of the registry or worker contract, but must be resolved from measured ZBook preflight data before a real local acceptance run:

1. The exact ZBook operating system, Docker version, available RAM, CPU count, and free disk.
2. The exact Ollama model tag and digest installed on the ZBook.
3. The maximum worker concurrency and per-worker CPU/memory/time budgets supported by measured resources.
4. The explicit 391-instance manifest and role distribution; it must come from a workload definition, not invented uniform role weights.
5. Which external integrations, if any, each specialist may access on the local workstation. Default is deny until explicitly allowlisted.
