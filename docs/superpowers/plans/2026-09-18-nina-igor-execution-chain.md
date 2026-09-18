# Nina / Igor Execution Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the missing NINA orchestration, bounded tool execution, provenance-aware verification, contradiction detection, replay, and human-gate interfaces on top of the existing OLA runtime without replacing its verified baseline.

**Architecture:** NINA owns task intake and bounded orchestration. OLA remains the execution/policy/evidence boundary. IGOR consumes the resulting evidence independently and verifies chain integrity, expected outcome, provenance, and replay data. Human Gate is an explicit terminal decision and never converts UNKNOWN into VERIFIED.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/SQLite, existing OLA hash-chain and evidence runtime, pytest, GitHub Actions.

**Spec:** Existing approved NINA/IGOR execution-chain design in chat; existing OLA provenance mutation gate at commit `2ce02f1dd6009c6221ab3a94a819927867d2547b` is the baseline and must remain intact.

## Global Constraints

- Preserve the existing OLA runtime and provenance gate; do not replace working components.
- No external LLM inference is claimed by the deterministic baseline.
- Tool execution is bounded by an explicit registry; unknown tools are denied.
- IGOR must be independently callable from NINA and must not trust NINA's final status.
- UNKNOWN/NOT_PROVEN must never be promoted to VERIFIED.
- Human approval is explicit and terminal; rejection blocks execution/result promotion.
- Every new production behavior gets a failing test before implementation.
- CI must verify the exact commit under test and publish machine-readable evidence.

---

### Task 1: NINA task contract and bounded tool registry

**Files:**
- Create: `app/nina.py`
- Create: `tests/test_nina.py`

**Interfaces:**
- `NinaTask(task_id, tenant_id, task, requested_tools)`
- `NinaDecision(status, reason, allowed_tools)`
- `NinaOrchestrator.plan(task)`
- `NinaOrchestrator.execute(task)`

- [ ] Write failing tests for deterministic task creation, empty-task rejection, and unknown-tool denial.
- [ ] Verify tests fail for the intended missing interfaces.
- [ ] Implement the minimal task contract and registry.
- [ ] Run the focused tests.
- [ ] Commit the task.

### Task 2: NINA execution adapter over existing OLA runtime

**Files:**
- Modify: `app/nina.py`
- Create: `tests/test_nina_runtime.py`

**Interfaces:**
- `NinaOrchestrator.execute(task)` returns OLA run id, evidence ids, and raw runtime result.

- [ ] Write failing tests proving NINA delegates execution to the existing runtime and does not invent VERIFIED status.
- [ ] Verify RED.
- [ ] Implement the adapter.
- [ ] Run focused and existing agent-runtime tests.
- [ ] Commit.

### Task 3: IGOR independent verifier

**Files:**
- Create: `app/igor.py`
- Create: `tests/test_igor.py`

**Interfaces:**
- `IgorVerifier.verify(tenant_id, run_id, expected_commit, expected_task, expected_result)`
- Returns a structured result with `status`, `reason`, `checks`, and evidence references.

- [ ] Write failing tests for clean verification, wrong commit, broken hash chain, wrong result, and missing evidence.
- [ ] Verify RED.
- [ ] Implement verification using existing chain primitives and direct database reads.
- [ ] Run focused tests.
- [ ] Commit.

### Task 4: Contradiction engine and replay contract

**Files:**
- Create: `app/contradiction.py`
- Create: `app/replay.py`
- Create: `tests/test_contradiction_replay.py`

**Interfaces:**
- `detect_contradictions(records)` returns stable contradiction findings.
- `build_replay(records)` returns an ordered replay object with input/output digests and tool decisions.
- Replay is descriptive and deterministic; it does not re-execute side effects.

- [ ] Write failing tests for contradictory terminal claims, missing sequence continuity, and deterministic replay output.
- [ ] Verify RED.
- [ ] Implement minimal detectors and replay serialization.
- [ ] Run focused tests.
- [ ] Commit.

### Task 5: Explicit Human Gate

**Files:**
- Create: `app/human_gate.py`
- Create: `tests/test_human_gate.py`

**Interfaces:**
- `HumanDecision(approved, actor, reason)`
- `HumanGate.evaluate(candidate_status, decision)`

- [ ] Write failing tests proving approval cannot promote UNKNOWN and rejection always blocks.
- [ ] Verify RED.
- [ ] Implement fail-closed gate.
- [ ] Run focused tests.
- [ ] Commit.

### Task 6: NINA → OLA → IGOR orchestration endpoint

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_nina_igor_e2e.py`

**Interfaces:**
- `POST /nina-run` accepts a task and optional requested tools.
- Response contains `run_id`, NINA decision, OLA execution status, IGOR verification, replay summary, and final gate status.

- [ ] Write failing E2E tests for clean execution and blocked provenance mutation.
- [ ] Verify RED.
- [ ] Implement the endpoint with fail-closed terminal status.
- [ ] Run all tests.
- [ ] Commit.

### Task 7: CI evidence for exact-commit NINA/IGOR verification

**Files:**
- Create: `.github/workflows/nina-igor-gate.yml`
- Create: `scripts/verify_nina_igor_gate.py`
- Create: `tests/test_nina_igor_ci_contract.py`

- [ ] Write failing contract tests for exact SHA binding and machine-readable evidence.
- [ ] Verify RED.
- [ ] Implement the CI verifier/workflow.
- [ ] Run local tests available in the repository.
- [ ] Push branch and inspect the resulting GitHub Actions run.
- [ ] Record exact run id, commit SHA, artifact name, and hash in the final evidence report.

### Task 8: Final independent verification

- [ ] Compare branch against baseline commit.
- [ ] Run full test suite through CI.
- [ ] Verify NINA, OLA, IGOR, provenance, replay, and human-gate statuses independently.
- [ ] Do not mark the chain VERIFIED if any required evidence is missing.
- [ ] Open a PR with the evidence summary.
