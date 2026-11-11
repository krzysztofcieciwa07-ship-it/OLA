# OLA Assurance Agent Team Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a sequential, evidence-driven specialist-agent team for OLA, beginning with a real test agent and a read-only orchestrator.

**Architecture:** A small Python package exposes typed context/report contracts, a SHA-256-chained lifecycle ledger, an allowlisted pytest specialist, a sequential orchestrator, and a CLI. GitHub Actions runs the team on pull requests and uploads the exact-SHA report bundle. Additional specialists are enabled only after their own implementation and tests.

**Tech Stack:** Python 3.12+, dataclasses, pathlib, hashlib, pytest, GitHub Actions.

## Global Constraints

- Bind every run and report to the exact 40-character source commit.
- Execute specialists sequentially in deterministic order.
- Continue gathering diagnostics after a specialist failure; overall status remains failed.
- Never promote missing or unavailable evidence to PASS or VERIFIED.
- Read-only operation: no production deployment, source mutation, merge, or secrets access.
- Test execution uses a fixed allowlist, `shell=False`, and a finite timeout.
- Keep raw test output out of uploaded artifacts; preserve only a bounded safe summary and digest.
- SHA-256 chaining proves post-generation integrity, not truthfulness of the observation.
- Legal agent output is not legal advice or a legal compliance certification.
- Not-yet-enabled specialists must be listed explicitly as not enabled.

---

### Task 1: Typed assurance contracts and verifiable event ledger

**Files:**
- Create: `app/assurance_team/__init__.py`
- Create: `app/assurance_team/contracts.py`
- Test: `tests/test_assurance_team.py`

**Interfaces:**
- `AgentContext(repo_root: Path, source_commit: str, timeout_seconds: int = 900)`
- `AgentReport(role: str, status: AgentStatus, findings: list, metrics: dict)`
- `AgentStatus`: PASS, FAIL, BLOCKED, UNKNOWN
- `verify_event_chain(events: list[dict]) -> bool`

- [x] **Step 1: Add focused failing tests.** The tests were committed before the implementation and exercised missing-module import, deterministic event sequence, source binding, and mutation detection.
- [x] **Step 2: Verify RED.** GitHub Actions run `42971267626`, job `130360046755`, failed during collection with `ModuleNotFoundError: No module named 'app.assurance_team'` (expected missing implementation).
- [ ] **Step 3: Implement contracts and ledger.** Validate full SHA-1 commit identifiers, use canonical JSON, chain each event to the prior hash, require one start and one terminal event, and reject malformed or reordered events.
- [ ] **Step 4: Verify focused pass.** Run `python -m pytest -q tests/test_assurance_team.py`; expect all focused tests to pass.
- [ ] **Step 5: Run integration check.** Run `python -m pytest -q tests/test_assurance_team.py tests/test_agent_runtime_finalization.py`; expect zero failures.
- [ ] **Step 6: Commit the passing deliverable.** Commit only package contracts and tests.

### Task 2: Read-only tester specialist

**Files:**
- Create: `app/assurance_team/tester.py`
- Modify: `tests/test_assurance_team.py`

**Interfaces:**
- `TesterAgent.run(context: AgentContext) -> AgentReport`
- Fixed allowlist: agent runtime, runtime finalization, agent safety gate, evidence concurrency, independent verifier tamper, NINA workflow gate/API, Ollama generation budget, runtime provenance.

- [ ] **Step 1: Verify behavior tests.** Assert the exact argv, no shell, repo cwd, finite timeout, output digest, and fail-closed behavior for test failures and timeouts.
- [ ] **Step 2: Implement the tester.** Do not accept arbitrary command strings or test paths from user input. Do not persist raw stdout/stderr.
- [ ] **Step 3: Verify focused pass.** Run `python -m pytest -q tests/test_assurance_team.py`; expect all tests to pass.
- [ ] **Step 4: Run the tester itself.** Run the allowlisted pytest suite through `TesterAgent`; expect PASS bound to the source SHA.
- [ ] **Step 5: Commit the passing deliverable.**

### Task 3: Sequential orchestrator and CLI evidence bundle

**Files:**
- Create: `app/assurance_team/orchestrator.py`
- Create: `app/assurance_team/cli.py`
- Modify: `tests/test_assurance_team.py`

**Interfaces:**
- `AgentOrchestrator(agents, planned_roles).run(context) -> dict`
- CLI: `python -m app.assurance_team.cli --repo-root . --source-commit "$GITHUB_SHA" --output-dir artifacts`

- [ ] **Step 1: Verify ordering and aggregation tests.** Agents run exactly in the supplied order; failures do not prevent later diagnostics; report is FAIL if any enabled specialist fails; absent roles are explicitly not enabled.
- [ ] **Step 2: Implement lifecycle.** Append `run.start`, paired specialist start/end, and `run.end`; include exact source SHA and independently recomputable event hashes.
- [ ] **Step 3: Write artifacts atomically.** Emit `team-report.json`, `team-events.jsonl`, and `team-events.sha256`. No report is written as successful if chain verification fails.
- [ ] **Step 4: Verify focused pass.** Run `python -m pytest -q tests/test_assurance_team.py`.
- [ ] **Step 5: Verify CLI.** Run the CLI with a test source SHA and temporary output directory; verify files exist, JSON parses, and the event chain re-verifies.
- [ ] **Step 6: Commit the passing deliverable.**

### Task 4: GitHub Actions integration

**Files:**
- Create: `.github/workflows/assurance-agent-team.yml`
- Create: `docs/assurance-team.md`

**Behavior:**
- Run on PRs to main, pushes to main, and manual dispatch.
- Use pinned action commit SHAs, `contents: read`, a finite timeout, no secrets, and concurrency isolation.
- Run the CLI at the exact checked-out commit.
- Upload the JSON report, JSONL events, and digest even when the agent result is non-zero, so failures remain inspectable.
- Fail the workflow for enabled agent failure or invalid evidence chain; show other roles as not enabled.

- [ ] **Step 1: Verify workflow syntax and path filters.**
- [ ] **Step 2: Add workflow and operator documentation.**
- [ ] **Step 3: Open/refresh the draft PR and inspect the exact-SHA Actions results.**
- [ ] **Step 4: Run the complete relevant test and security gates; record actual status without implying production deployment.**

## Later specialist slices

After the first slice is green, add specialists one at a time in this order: architecture, performance, protection/security, legal/compliance. Only then enable the full six-role plan in the orchestrator. Each specialist gets a concrete evidence input, bounded scope, focused tests, and a documented UNKNOWN/BLOCKED state when its required evidence is unavailable.
