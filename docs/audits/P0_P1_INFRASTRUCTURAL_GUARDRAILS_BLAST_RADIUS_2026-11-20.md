# P0/P1 Infrastructural Guardrails & Blast-Radius Isolation Contract

Date: 2026-11-20
Scope: OLA di-OS agent action execution architecture. This document defines an auditable contract and proposed tests; it does **not** claim controls are deployed or verified.

## Security premise
Treat every model proposal, including tool arguments and model-produced structured output, as untrusted input. A planner may request an action; it cannot authorize or execute it directly. Authorization and execution containment are infrastructure decisions.

## Reference flow
LLM/Planner -> strict action schema -> deterministic policy engine -> capability broker -> isolated executor -> independent result verification -> lifecycle evidence.

No direct model path to database, shell, filesystem, network, credentials, or other privileged resources. Any bypass path is a P0 finding.

## Guardrails and evidence

| Guardrail | Enforceable contract | Required evidence |
|---|---|---|
| Capability whitelist | Explicit versioned registry (e.g. capabilities.json); only registered capability IDs and schemas can be invoked. Registry is not itself authorization. | Registry hash/version, code review, negative unknown-capability tests |
| Atomic authorization | Policy evaluates capability, arguments, session/user identity, tenant, resource scope, environment, risk class, expiry and approval state before execution. | Policy decision record and test vectors; deny-by-default |
| Scope-bound credentials | Broker issues or obtains short-lived credentials scoped to the single action, tenant/resource, and operation; no broad ambient credential in model/executor. | IAM/secret-manager evidence, token scope/TTL, redacted audit |
| Deterministic enforcement | No LLM or probabilistic decision inside authorization. Missing, malformed, stale, conflicting or unverifiable policy context => REJECT. | Deterministic unit/property tests and policy version trace |
| Executor isolation | Separate process/container or stronger boundary; no host privileges; read-only mounts by default; resource quotas; restricted syscalls where applicable. | Runtime config, isolation tests, host escape/permission tests in controlled environment |
| Network allowlist | Egress denied by default; destinations/protocols explicitly allowlisted and DNS/IP changes controlled. | Firewall/network policy and negative connection tests |
| Execution limits | Hard timeout, bounded steps, memory/CPU, output size, recursion/depth, rate and cost limits. Cancellation is enforced externally. | Limit tests, kill/cancel proof and metrics |
| Safe state | Fail closed on policy/broker/executor/verifier failure; stop action, revoke/expire capability, quarantine uncertain state. Rollback only where semantics permit; otherwise reconcile. | Fault injection, state transition evidence and recovery runbook |
| Approval boundary | Irreversible/high-impact actions require independent human approval with action hash, scope and expiry; approval cannot be broadened after signing. | Approval binding tests and audit trail |
| Evidence lifecycle | run.start -> authorization -> execution -> verification -> run.end; records include action hash, capability/policy versions, identity, scope, outcome, timestamps and correlation ID. | Tamper detection, lifecycle completeness/reconciliation |
| Blast-radius control | Per-tenant/resource boundaries, disposable test target, quotas, circuit breaker and kill switch; no global mutable credential. | Cross-tenant denial tests and controlled kill-switch tests |

## Atomic capability request contract
A request must be bound to: capability_id, schema_version, normalized arguments, tenant_id, principal/session, resource scope, environment, request/run ID, policy version, expiry, risk class and approval reference (if required). The broker must reject replay, stale authorization, scope expansion, unknown fields and any mismatch between approved and executed action hash.

## Negative testing suite (P0/P1)
Tests must demonstrate denial, not merely successful execution:
1. Unknown capability ID -> REJECT; executor not invoked.
2. Missing/expired/revoked token -> REJECT; no side effects.
3. Tenant A credential/request targeting Tenant B -> REJECT.
4. Argument/resource scope exceeds grant -> REJECT.
5. Policy engine unavailable or decision indeterminate -> REJECT (fail-closed).
6. Broker unavailable -> REJECT and safe state; no fallback direct tool route.
7. Executor network access to non-allowlisted destination -> blocked at infrastructure layer.
8. Timeout/resource budget exceeded -> externally enforced stop; record final state.
9. Tool output is malformed, oversized, adversarial or inconsistent -> validation/quarantine; no chained action without reauthorization.
10. Replay of prior action/approval -> reject unless an explicit idempotency contract permits it.
11. Approval altered, action hash changed or approval expired -> reject.
12. Parallel actions race to exceed tenant/resource quotas -> limit enforced.
13. Cancellation/kill switch during execution -> verify containment and reconciliation semantics.
14. Attempted direct DB, shell, filesystem or credential access from planner context -> denied; capability boundary holds.
15. Lifecycle record missing, duplicated or unverifiable -> run cannot be marked verified/successful.

## Required test evidence
For each test: exact code revision, environment/target identity, test input hash, expected deny condition, observed result, side-effect probe, log/evidence reference, timestamps, and independent reviewer or CI attestation. Synthetic tests establish behavior of the test target only; they do not establish production isolation.

## Gate
P0/P1 gate remains BLOCKED until the guardrails are implemented, tests execute against the exact candidate revision, deployed configuration is independently inspected, and evidence shows denial paths have no unintended side effects. This document alone is architecture/specification evidence, not implementation or runtime proof.
