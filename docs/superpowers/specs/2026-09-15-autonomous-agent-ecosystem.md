# Autonomous Agent Ecosystem — Verification Contract

## Scope

This specification defines what must be proven before OLA-di-OS can claim:

1. six autonomous AI agents;
2. 391 cooperating agents;
3. production-scale autonomy;
4. a production product built on the core.

The current six-role deterministic runtime is the baseline, not the target proof.

## Required evidence

### Six autonomous agents

Each of six agents must have:

- unique stable `agent_id`;
- unique execution/process identity;
- isolated execution context;
- explicit model/provider invocation;
- capability and tool boundary;
- input/output evidence;
- communication or handoff evidence where cooperation is claimed;
- independently verifiable execution record.

A loop over six role names, UUIDs, or synthetic contexts alone is insufficient to establish autonomous-agent status.

### 391 cooperating agents

A verified 391-agent run requires:

`391 unique identities -> 391 executions -> task decomposition -> communication/dependency graph -> 391 evidence records -> complete hash chain -> independent verifier -> CI artifact`.

The verifier must reject duplicate identities, missing executions, broken dependencies, tampering, incomplete evidence, and run-count mismatches.

### Production-scale autonomy

Production-scale status requires runtime evidence for:

- bounded concurrency;
- persistence across restart;
- recovery after worker/tool failure;
- tenant isolation;
- observable execution;
- repeatable verification;
- resource/time limits;
- security and authorization boundaries.

Passing unit tests or a single controlled CI run does not by itself establish production scale.

### Production product

Production-product status requires:

- deployed product surface;
- real authentication/tenant boundary;
- real external model/tool boundary where claimed;
- real user task;
- independently verified result;
- customer acceptance or usage evidence;
- real billing/checkout evidence for revenue claims.

Synthetic invoice fixtures and deterministic test models remain test evidence only.

## Product architecture

`OLA-di-OS` is the shared core. `LegalMesh` and `SentinelOps` are vertical modules that consume the core orchestration, execution, evidence, verification, and governance services.

```text
OLA-di-OS Core
├── Routing / Orchestration
├── Agent Registry / Scheduler
├── Agent Execution Boundary
├── Memory / Context
├── Tool / MCP Boundary
├── Evidence Vault
├── Verification / Policy Gate
└── Observability / Recovery
    ├── LegalMesh
    └── SentinelOps
```

## Financial evidence

CAC, LTV, CAC payback, and LTV/CAC must be calculated from real customer data before being labelled VERIFIED. Any illustrative values must be labelled `SYNTHETIC / MODEL ONLY`.

## Non-negotiable claim boundary

`6 verified role executions != 6 autonomous AI agents != 391 agents != production-scale autonomy != production product != revenue.`
