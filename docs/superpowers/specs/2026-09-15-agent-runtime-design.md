# Agent Runtime Design

**Goal:** Add a minimal evidence-first six-agent runtime to the existing OLA execution gate and prove it through tests, CI, real container execution, durable evidence, and an independent verifier.

## Scope

The runtime will expose one task execution path. Six agent roles execute deterministic contracts representing the requested patterns: CodeAct, ReAct, Agentic RAG, MCP/tool use, self-reflection, and multi-agent orchestration. This first gate proves orchestration and provenance; it does not claim autonomous LLM reasoning where no model/tool integration exists.

## Runtime contract

`TASK -> ORCHESTRATOR -> AGENT_1..AGENT_6 -> EVIDENCE -> INDEPENDENT VERIFIER -> DECISION`

Each agent emits an evidence record containing agent name, input digest, output digest, action/result, status, and sequence. Evidence is append-only and hash-chained by the existing evidence layer.

## Safety / truth rules

- UNKNOWN never becomes ALLOW.
- Failed or missing evidence produces `UNKNOWN` or `BLOCK`, never `VERIFIED`.
- The independent verifier must recompute the evidence chain instead of trusting the orchestrator result.
- The first implementation uses deterministic local agent contracts; LLM calls and external MCP tools remain explicit future integrations and are not represented as VERIFIED until runtime-tested.

## Success gate

A run is VERIFIED only when all six agents execute, all required evidence records exist, the independent verifier recomputes the chain successfully, and CI proves the same flow inside the deployment container. CI must upload durable runtime evidence bound to the exact commit SHA.
