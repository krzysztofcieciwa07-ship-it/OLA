# OLA di-OS — Zero Trust for Agent Intent

Date: 2026-11-20
Status: Architectural contract / implementation gate
Scope: Agent-originated actions in OLA di-OS

## Core axiom
**Agent = Untrusted Intent Source (Unreliable Oracle). Broker = Deterministic Gatekeeper.**

The system must not require the model to behave correctly for security to hold. Model output is input, not authorization. The model can propose; infrastructure decides, constrains, executes and verifies.

## Zero Trust action loop
1. Request: Planner emits a typed proposal. It has no ambient authority.
2. Validate: Strict schema, canonicalization, bounds, allowlisted capability identifier; reject unknown fields or malformed data.
3. Authenticate: Resolve principal/session and workload identity independently of model output.
4. Authorize: Deterministic policy evaluates capability, tenant, resource, operation, environment, risk, expiry, quotas and approval.
5. Bind: Authorization is bound to normalized action hash, resource scope, identity, policy version, run ID, expiry and idempotency key.
6. Broker: Broker issues only the narrowly scoped execution capability; no direct privileged tool route.
7. Execute: Isolated executor applies network/filesystem/database/process limits and externally enforced timeout/cancellation.
8. Verify: Independent verifier checks actual outcome and expected state transition; tool output alone is not proof.
9. Record: Lifecycle evidence is correlated and integrity-checked. Missing or inconsistent evidence means UNVERIFIED, not SUCCESS.
10. Contain: On uncertain authorization, broker/executor/verifier failure, revoke/expire capability, stop further actions and enter safe state; reconcile irreversible effects.

## Trust invariants
- No implicit trust: Network location, model quality, previous successful actions and tool responses confer no authorization.
- Deny by default: Unknown capability, missing context, policy outage, malformed input or ambiguity => REJECT.
- No authority in prompts: System/developer prompts are not enforcement boundaries.
- No direct access: Planner/model has no direct credentials or direct route to protected resources.
- Scope immutability: Scope cannot widen after authorization or approval.
- Action binding: Approved and executed action hashes must match after canonicalization.
- Independent enforcement: Executor limits, network rules and isolation are enforced outside the LLM.
- Fail closed, fail safely: Block new work on uncertain state; use rollback only when technically valid, otherwise quarantine and reconcile.
- Evidence is not trust: Evidence must be independently collected/reconciled; an agent-written log alone is insufficient.
- Least privilege and short lifetime: Grant minimum permissions for one operation and revoke/expire promptly.
- Bounded blast radius: Tenant/resource isolation, concurrency quotas, rate limits, budgets and kill switches.

## Policy decision tuple
The policy engine must deterministically evaluate a request bound to: principal and session/workload identity; tenant and resource identifier; capability ID and version; normalized argument hash and validated schema; environment and target; risk classification and required approval; token/capability expiry and revocation state; quota, rate and execution budget; policy version; run ID and idempotency key.

A policy decision should return a structured decision (ALLOW or REJECT), reason code, policy version, decision ID, and constraints. It must not return a broadly reusable permission.

## Mandatory negative tests
These are proposed gate requirements and must be run against the exact candidate code and controlled target:
- unknown capability / schema version;
- absent, expired, revoked or wrong-principal credential;
- cross-tenant or cross-resource request;
- altered arguments/action hash after approval;
- replay / duplicate / stale request;
- policy or broker timeout/unavailability;
- allowlist miss and DNS/network destination drift;
- executor resource limit, timeout, cancellation and kill switch;
- output schema failure, oversized output, malicious content and verifier disagreement;
- direct privileged-access attempt from planner/executor;
- concurrent requests exceeding quotas;
- missing, duplicate or tampered lifecycle evidence;
- recovery/reconciliation following ambiguous or irreversible outcome.

For each case, capture expected denial/containment, actual side-effect probe, target identity, exact commit, test input/output hashes, timestamps, evidence references and reviewer/CI identity.

## Status and acceptance
This document defines architecture and acceptance criteria only. It does not certify current OLA implementation or deployed isolation. The gate remains BLOCKED until implemented controls are independently reviewed, negative tests pass on the exact candidate, and deployed configuration/identity/network evidence is reconciled.
