# Autonomous Agent Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the verified six-role deterministic runtime into a production-oriented agent execution fabric that can prove real agent-process boundaries, support 391 cooperating executions, and expose OLA-di-OS as the shared core for LegalMesh and SentinelOps without claiming unproven autonomy.

**Architecture:** OLA-di-OS remains the core orchestration and evidence platform. Agent execution is moved behind a provider/worker boundary so each agent execution has an explicit identity, context, communication envelope, capability contract, and independently verifiable evidence. A registry and scheduler will support arbitrary agent counts, including a controlled 391-agent test, while production claims require runtime/load/recovery/customer evidence.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, GitHub Actions, existing append-only evidence/hash-chain store.

**Spec:** `docs/superpowers/specs/2026-09-15-autonomous-agent-ecosystem.md`

## Global Constraints

- No UNKNOWN claim may be promoted to VERIFIED without fresh evidence.
- Six role executions are not equivalent to six autonomous AI agents.
- A 391-agent test must prove 391 unique identities/executions and cooperation evidence.
- Production-scale autonomy requires runtime/load/restart/recovery evidence, not static code.
- Real customer and revenue claims require external business evidence.
- Existing evidence/hash-chain and independent-verifier guarantees must remain intact.
- Test fixtures must be explicitly synthetic/controlled.

---

### Task 1: Agent execution boundary contract

**Files:**
- Create: `docs/superpowers/specs/2026-09-15-autonomous-agent-ecosystem.md`
- Test: `tests/test_agent_execution_boundary.py`

**Interfaces:**
- Produces an explicit execution contract for agent identity, context, capability, communication, model invocation, and evidence.

- [ ] Write failing tests for unique process/instance identity and explicit provider metadata.
- [ ] Run the targeted test and record the expected failure.
- [ ] Define the contract in the spec and test fixtures.
- [ ] Run the targeted test again.

### Task 2: Worker-backed agent runtime

**Files:**
- Create: `app/agent_worker.py`
- Modify: `app/agent_runtime.py`
- Test: `tests/test_agent_worker_runtime.py`

**Interfaces:**
- `run_agent_worker(agent_id, task, context) -> AgentExecution`
- `AgentExecution` contains agent identity, context digest, provider/model metadata, output, and communication metadata.

- [ ] Write failing tests proving worker boundary and independent execution identity.
- [ ] Run targeted tests and verify RED.
- [ ] Implement the smallest worker boundary.
- [ ] Run targeted tests and verify GREEN.
- [ ] Preserve the existing evidence/hash-chain contract.

### Task 3: Agent registry and 391-agent orchestration

**Files:**
- Create: `app/agent_registry.py`
- Modify: `app/agent_runtime.py`
- Test: `tests/test_391_agent_runtime.py`

**Interfaces:**
- `build_agent_registry(count) -> list[AgentSpec]`
- `run_multi_agent_task(..., agent_specs) -> run evidence`

- [ ] Write failing test requiring exactly 391 unique agent identities.
- [ ] Verify RED.
- [ ] Implement registry and bounded scheduler.
- [ ] Verify GREEN for 391 controlled executions.
- [ ] Add cooperation/dependency evidence and independent verification.

### Task 4: Independent 391-agent verifier

**Files:**
- Create: `scripts/verify_391_agent_runtime.py`
- Test: `tests/test_independent_391_verifier.py`

**Interfaces:**
- Standalone verifier must not import runtime verification code.
- Exit 0 only for a complete verified 391-agent evidence graph.
- Exit nonzero with `BLOCK` for missing, duplicated, reordered, or tampered evidence.

- [ ] Write tamper and omission tests first.
- [ ] Verify RED.
- [ ] Implement independent verification and full-chain integrity checking.
- [ ] Verify GREEN.

### Task 5: Production-scale runtime gate

**Files:**
- Modify: `.github/workflows/e2e.yml`
- Create: `tests/test_production_scale_gate.py`

**Interfaces:**
- CI proves bounded concurrency, persistence, restart/recovery, and deterministic evidence collection.

- [ ] Write failing production-gate assertions.
- [ ] Verify RED.
- [ ] Implement only the minimum runtime hooks needed.
- [ ] Verify GREEN locally/CI.
- [ ] Add artifact capture and provenance.

### Task 6: Product core / vertical modules

**Files:**
- Create: `app/products/legalmesh.py`
- Create: `app/products/sentinelops.py`
- Create: `tests/test_product_modules.py`
- Modify: `README.md`

**Interfaces:**
- Both modules consume the shared OLA-di-OS core rather than duplicate orchestration/evidence logic.

- [ ] Write failing integration tests for shared-core usage.
- [ ] Verify RED.
- [ ] Implement minimal module adapters.
- [ ] Verify GREEN.
- [ ] Update product architecture documentation.

### Task 7: Revenue evidence gate

**Files:**
- Create: `tests/test_revenue_evidence_gate.py`
- Modify: `.github/workflows/e2e.yml`

**Interfaces:**
- CI may validate the calculation model, but real CAC/LTV/payback remains UNKNOWN until supplied by real customer/payment data.

- [ ] Add a test that rejects unlabeled synthetic financial claims.
- [ ] Verify RED.
- [ ] Implement explicit evidence classification.
- [ ] Verify GREEN.

### Task 8: Final verification

**Files:**
- No code changes unless failures require them.

- [ ] Run the complete pytest suite.
- [ ] Run the complete GitHub Actions E2E workflow.
- [ ] Download the resulting artifact.
- [ ] Independently recompute artifact SHA-256.
- [ ] Verify provenance commit -> CI run -> artifact.
- [ ] Run the standalone 391-agent verifier against captured evidence.
- [ ] Publish only claims supported by fresh evidence.
