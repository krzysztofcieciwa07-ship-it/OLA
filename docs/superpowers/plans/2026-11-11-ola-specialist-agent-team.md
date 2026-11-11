# OLA Specialist Agent Team Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Introduce six least-privilege specialist roles that emit independently verifiable, source-bound evidence, delivered one specialist at a time.
**Architecture:** Add a small versioned contract and role registry, then implement each specialist as a bounded capability over existing OLA services and CI workflows. An independent verifier checks schema, source SHA, lifecycle closure, evidence references, digests, and side-effect policy; orchestration is added last.
**Tech Stack:** Existing Python 3.12/3.13, FastAPI, SQLAlchemy, pytest, GitHub Actions, evidence ledger, NINA/IGOR.
**Spec:** docs/specs/2026-11-11-ola-specialist-agent-team-design.md

## Global Constraints
- Preserve NINA/IGOR, evidence ledger, Human Gate, and release boundaries.
- No production deploy, PR merge, legal sign-off, or policy override by agents.
- LLM output is advisory; deterministic code enforces state transitions and permissions.
- Reports bind to exact source SHA, role version, task digest, evidence references, and artifact digests.
- Unknown or unverifiable results fail closed; no secrets or raw customer personal data in artifacts.
- Reuse existing CI instead of duplicating full pytest.

## Review Focus
- Missing terminal lifecycle record never becomes VERIFIED; test duplicate finalization and retry.
- Wrong or stale source SHA is rejected.
- Malformed, oversized, or deeply nested input is rejected within strict limits.
- Cross-tenant report/evidence access is denied.
- Agent-reported test pass without real successful process exit and retained logs is rejected.

---

### Task 1: Shared report contract and bounded role registry
Files: create app/specialist_agents/contracts.py; app/specialist_agents/registry.py; tests/test_specialist_agent_contracts.py; tests/test_specialist_agent_registry.py.
Interfaces: validate_task(payload: dict) -> TaskContract; validate_report(payload: dict) -> SpecialistReport; get_specialist(role: str) -> SpecialistDefinition. Roles: test, architecture, performance, security, legal, orchestration. Definitions include version, capability allowlist, timeout, input/output limits, and side-effect class.
- [ ] Write tests for valid schema, unknown role, extra fields, depth/size limits, immutable capability allowlists.
- [ ] Run focused tests and record expected red failures.
- [ ] Implement minimal contracts and registry.
- [ ] Run focused and relevant existing runtime/evidence tests.
- [ ] Commit shared contract slice on feature branch.

### Task 2: Test specialist — first deployable agent
Files: create app/specialist_agents/test_agent.py and tests/test_specialist_test_agent.py; modify .github/workflows/nina-tdd.yml or add a narrowly scoped workflow only if existing triggers cannot support the task. Reuse tests/, scripts/verify_agent_runtime.py, E2E and provenance gates.
Interface: run_test_agent(task: TaskContract) -> SpecialistReport. Test selection is allowlisted; arbitrary shell commands forbidden. Report includes exact test IDs, command profile, exit code, counts, source SHA, log artifact digest, and terminal status.
- [ ] Tests prove non-zero exit => BLOCKED/FAILED, missing logs => BLOCKED, stale SHA => rejected, exact successful run => candidate report.
- [ ] Run focused tests to establish red.
- [ ] Implement bounded test profiles using subprocess argument arrays, timeouts, output caps, sanitized logs.
- [ ] Add independent report verification; only verifier promotes candidate to VERIFIED.
- [ ] Run focused tests, runtime/evidence tests, and selected existing CI workflows on exact branch SHA.
- [ ] Review permissions and artifact retention; commit and open draft PR only after verification.

### Task 3: Architecture specialist
Files: create app/specialist_agents/architecture_agent.py and tests/test_specialist_architecture_agent.py.
- [ ] Test source binding, file/line references, and fact/inference separation.
- [ ] Implement bounded static inspection of imports, routes/schema contracts, dependency manifests, and architecture records.
- [ ] Verify each finding references a real file and line in inspected SHA; run tests and commit.

### Task 4: Performance specialist
Files: create app/specialist_agents/performance_agent.py and tests/test_specialist_performance_agent.py.
- [ ] Test sample size, environment, percentile, timeout, and baseline comparability.
- [ ] Implement bounded load/profile scenarios with explicit concurrency and duration ceilings.
- [ ] Reject incompatible environment/workload comparisons; run tests and commit.

### Task 5: Security specialist
Files: create app/specialist_agents/security_agent.py and tests/test_specialist_security_agent.py.
- [ ] Test tenant scope, severity mapping, allowlisted scanners, secret redaction, and fail-closed findings.
- [ ] Reuse CodeQL, dependency, auth, isolation, network allowlist, and evidence outputs.
- [ ] Require reproducible evidence for actionable findings; run tests and commit.

### Task 6: Legal specialist
Files: create app/specialist_agents/legal_agent.py and tests/test_specialist_legal_agent.py.
- [ ] Test that output cannot be represented as legal advice, certification, or human approval.
- [ ] Implement structured issue-spotting checklist for privacy, retention, processors, terms, jurisdiction.
- [ ] Require source references and explicit human/legal review; run tests and commit.

### Task 7: Orchestration specialist
Files: create app/specialist_agents/orchestration_agent.py and tests/test_specialist_orchestration_agent.py.
- [ ] Test dependency order, budgets, retries, partial failure, conflicting findings, and no self-approval.
- [ ] Implement sequential orchestration first; parallelism only for independent read-only tasks.
- [ ] Aggregate immutable reports without changing contents.
- [ ] Any BLOCKED/FAILED/PENDING_REVIEW specialist prevents overall VERIFIED.
- [ ] Run full specialist suite and relevant existing CI; commit.

### Task 8: End-to-end assurance and staging rollout
Files: create tests/test_specialist_team_e2e.py and docs/operations/specialist-agent-runbook.md; modify workflows only after contracts stabilize.
- [ ] Test task -> specialist -> evidence -> independent verification -> summary lifecycle.
- [ ] Test tamper, replay, duplicate submission, tenant isolation, timeout, partial outage.
- [ ] Run required checks on exact candidate SHA.
- [ ] Deploy to staging only; verify health continuously across an agreed stability window.
- [ ] Keep production blocked until human review and release authorization.