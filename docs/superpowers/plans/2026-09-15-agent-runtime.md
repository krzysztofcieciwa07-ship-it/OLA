# Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and prove a minimal six-agent evidence-first runtime.

**Architecture:** A single orchestrator runs six deterministic agent contracts, writes append-only hash-chained evidence, then invokes an independent verifier. The deployment container runs the same path under CI.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-15-agent-runtime-design.md`

## Global Constraints

- No production code without a failing test first.
- UNKNOWN never becomes VERIFIED or ALLOW.
- Independent verification recomputes evidence rather than trusting the orchestration result.
- No claim of real LLM/MCP autonomy until those integrations are actually executed and evidenced.
- Existing E2E gate must remain green.

---

### Task 1: Agent contract and orchestration tests

**Files:**
- Create: `tests/test_agent_runtime.py`
- Create: `app/agent_runtime.py`

- [ ] Write failing tests for six ordered agent roles, evidence output, verifier rejection on missing evidence, and successful six-agent run.
- [ ] Run the new tests and confirm the expected failures.
- [ ] Implement the smallest role contract and orchestrator that satisfies the tests.
- [ ] Run the new tests and the existing suite.
- [ ] Commit.

### Task 2: HTTP runtime endpoint

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_agent_runtime.py`

- [ ] Add a failing HTTP test for `/agent-run`.
- [ ] Verify failure.
- [ ] Add the endpoint using the existing tenant/evidence infrastructure.
- [ ] Verify all tests pass.
- [ ] Commit.

### Task 3: Independent runtime verifier

**Files:**
- Create: `scripts/verify_agent_runtime.py`
- Modify: `tests/test_agent_runtime.py`

- [ ] Add tests proving verifier independently checks six agents and the hash chain.
- [ ] Verify RED.
- [ ] Implement verifier.
- [ ] Verify GREEN.
- [ ] Commit.

### Task 4: CI and durable runtime evidence

**Files:**
- Modify: `.github/workflows/e2e.yml`

- [ ] Add a CI step that runs `/agent-run` against the real Docker container.
- [ ] Run independent verifier against SQLite evidence.
- [ ] Bind proof to `${{ github.sha }}`.
- [ ] Capture verifier output, container logs, DB/file hashes, and provenance.
- [ ] Upload an artifact named with the exact commit SHA.
- [ ] Commit.

### Task 5: Final verification

- [ ] Confirm the push workflow run exists for the exact implementation commit.
- [ ] Confirm every agent-runtime CI step is successful.
- [ ] Confirm artifact exists and is bound to the same commit SHA.
- [ ] Confirm independent verifier result is VERIFIED.
- [ ] Only then promote the agent runtime gate to VERIFIED.
