# OLA Specialist Agent Team — Design Specification

Status: Proposed implementation baseline; user requested sequential construction.

## Goal
Build six bounded specialist roles that produce independently verifiable, tenant-scoped findings tied to an exact source revision. Agent self-reported success is never proof.

## Existing-system constraints
- Preserve the FastAPI runtime and current NINA, IGOR, evidence, Human Gate, and release boundaries.
- Reuse existing CI, E2E, provenance, replay, and security workflows; do not duplicate the full test suite.
- Every run records run.start and run.end (or explicit pending/failed state), source commit, role/version, task digest, outcome, and evidence references.
- Unknown, incomplete, contradictory, or unverifiable states fail closed; never promote them to VERIFIED.
- Least-privilege capability allowlists; no self-granted permissions.
- No agent may merge code, deploy production, approve its own findings, or bypass Human Gate.
- Reports distinguish observed facts, inferred risks, and recommendations.
- LLM output is advisory; deterministic code and independent verification enforce decisions.
- Bound input/output size, nesting, time, retries, and network destinations. Do not expose secrets or raw customer personal data.

## Specialist responsibilities
1. Test: run allowlisted tests and regression/security scenarios; report exact test IDs, commands, exit codes, counts, source SHA, and artifact digests.
2. Architecture: inspect module boundaries, dependency direction, API/schema contracts, versioning, and drift; findings cite exact files and lines.
3. Performance: run bounded load/profile scenarios; report percentiles, throughput, resources, sample size, environment, and comparable baseline.
4. Security: inspect auth, authorization, tenant isolation, input boundaries, network allowlists, secrets, dependencies, and fail-closed behavior.
5. Legal: issue-spot privacy, retention, processors/subprocessors, terms, and jurisdictional questions; no legal advice or certification; require human/legal review.
6. Orchestration: decompose objectives, assign registered tasks, enforce order/budgets, collect immutable reports, detect conflicts, and publish aggregate status. Cannot alter evidence or override blocks.

## Trust and execution model
- Versioned JSON Schema for task requests, specialist reports, and orchestration summaries.
- Registry fixes role version, capability allowlist, input/output limits, timeout, retry policy, and side-effect class.
- State machine: QUEUED -> RUNNING -> VERIFYING -> VERIFIED | BLOCKED | FAILED | PENDING_REVIEW.
- Independent verifier checks schema, exact source SHA, lifecycle closure, evidence references, digests, and policy.
- Hash chains prove integrity, not truth; external observations retain source and timestamp.
- Parallelism is opt-in and read-only only for independent tasks; side effects remain sequential and approval-gated.

## Delivery sequence
1. Test specialist.
2. Architecture specialist.
3. Performance specialist.
4. Security specialist.
5. Legal specialist.
6. Orchestration specialist, integrating the proven roles last.
The shared report contract and minimal role registry are prerequisites in the first slice. Do not build a generic platform before the first specialist works end-to-end.

## Acceptance criteria
- Each role accepts a schema-valid task and emits a schema-valid report.
- Every report binds to exact source SHA, role version, task digest, evidence references, and artifact digests.
- Independent verification rejects missing terminal events, invalid digests, wrong SHA, malformed reports, fabricated test-pass claims, and unapproved side effects.
- Test specialist cannot report VERIFIED if any required test fails or its logs are missing.
- Tenant A cannot read or mutate Tenant B tasks, reports, or evidence.
- New behavior has focused red-green tests; relevant existing suites remain green.
- Production remains blocked until staging health is stable for a defined observation window and human approval is recorded.

## Non-goals
- Six unrestricted LLM personas with shell/network access.
- Autonomous legal sign-off, production deployment, or merge.
- Replacing NINA/IGOR or duplicating the CI suite.
- Claiming full autonomy because six roles are registered.