# OLA Assurance Agent Team — Design

**Date:** 2026-11-11  
**Status:** Approved direction; implementation staged behind pull request #207.

## Goal

Build a controlled team of specialist assurance agents that inspect OLA in a fixed, auditable sequence and produce source-bound evidence. The team must distinguish a successful check from a missing capability, an inconclusive check, and a failure.

## Roles

- **Tester:** executes a fixed allowlist of runtime, safety, evidence, replay, and workflow tests.
- **Architecture:** inspects Python package structure, import dependencies, route contracts, and architecture-boundary rules.
- **Performance:** consumes reproducible load/latency measurements and reports SLI breaches; it does not infer production performance from a local smoke test.
- **Protection/Security:** inspects security controls, workflow permissions, dependency and secret-scanning evidence, and fail-closed boundaries.
- **Legal:** checks the presence and completeness of required legal/compliance evidence. It cannot declare legal compliance or replace qualified counsel.
- **Orchestration:** schedules enabled specialists sequentially, records lifecycle events, aggregates statuses, and publishes the evidence bundle. It cannot override a specialist failure or authorize production deployment.

## Architecture

The first slice is a small Python package under `app/assurance_team/`. Each specialist implements a common `run(context) -> AgentReport` interface. `AgentOrchestrator` invokes enabled agents in an explicit order and continues after a specialist failure so the full diagnostic picture is collected.

A report is bound to the exact 40-character source commit. The event ledger records `run.start`, `agent.start`, `agent.end`, and `run.end`; each event hash is SHA-256 over canonical JSON plus the previous event hash. An independent verifier recomputes the chain and validates lifecycle ordering. The digest proves artifact integrity after generation, not the truth of source observations.

The initial release enables only the tester. Other specialist roles remain visibly listed as not enabled; they are not represented by empty or synthetic passes. Each role will be implemented and reviewed in a separate slice.

## Security and operating boundaries

- GitHub Actions permissions are read-only (`contents: read`); no deployment credentials or production secrets are needed.
- The tester invokes Python/pytest with a hard-coded test-path allowlist, `shell=False`, a timeout, and no caller-supplied command string.
- Reports omit raw test output and store only a bounded summary and output digest.
- The agents perform repository inspection and test execution only. They do not edit application code, merge PRs, deploy, delete data, or change access controls.
- Agent results use `PASS`, `FAIL`, `BLOCKED`, or `UNKNOWN`. Missing evidence is never a pass.
- Legal findings are advisory control-gap observations, not a legal opinion.
- Production deployment remains a separate human-approved operation.

## Initial acceptance

1. The focused tests demonstrate RED before implementation and GREEN afterward.
2. The tester runs only its fixed test allowlist and fails closed on non-zero exit or timeout.
3. The orchestrator executes enabled agents sequentially, continues after failure, and binds all reports to the source SHA.
4. Evidence-chain mutation or incomplete lifecycle is rejected.
5. GitHub Actions emits a JSON report, JSONL event ledger, and SHA-256 manifest as an artifact.
6. A missing specialist is reported as not enabled, never as passing.
