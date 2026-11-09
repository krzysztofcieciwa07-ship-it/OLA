# Execution Quality, Chronology and Forensic Evidence Protocol

**Version:** 1.0  
**Effective date:** 2026-11-09  
**Status:** Operational engineering protocol. It is not a certification or a claim that every repository already complies.

## 1. Non-negotiable rule

A task is not complete because a plan, explanation, code draft, report, or pull request exists.

A task may be reported as **DONE** only when:
1. its acceptance criteria were stated before execution;
2. the required change or operation was actually performed;
3. verification was run against the exact resulting revision/environment;
4. results and relevant evidence were preserved;
5. a critical self-review found no unresolved blocker against the acceptance criteria;
6. all material failures were fixed and the relevant verification was repeated;
7. any required independent approval was obtained.

If one of these conditions is unmet, use an honest state such as `PARTIAL`, `BLOCKED`, `FAILED`, or `UNKNOWN`. Do not convert absence of evidence into success.

## 2. Task contract before execution

Every material task receives a unique immutable `task_id` and a compact contract:

- **Objective:** the user-visible outcome, not the activity.
- **Scope:** repositories, services, files, environments and identities included.
- **Out of scope:** explicit exclusions and unavailable systems.
- **Baseline:** repository full name, branch, full commit SHA, deployment/environment identifier and initial state where relevant.
- **Acceptance criteria:** observable, binary where possible, measurable and independently checkable.
- **Risk class:** low, medium, high or critical; include data loss, security, financial, availability and privacy impact.
- **Authorization boundary:** what is allowed automatically, what requires approval, and what is prohibited.
- **Verification plan:** tests, commands, expected outputs, runtime checks and evidence destinations.
- **Rollback/recovery:** a safe recovery path for consequential changes.

Do not begin a destructive or externally consequential action without the required authority and recovery plan. Read-only inspection and reversible changes to an isolated working branch can proceed within the authorised scope.

## 3. Chronology and event ledger

Record events in UTC using RFC 3339 timestamps with explicit timezone, for example `2026-11-09T09:30:00Z`.

For every material event record:
- `task_id`, monotonically increasing `sequence`, event type and timestamp;
- actor/service identity and execution context;
- repository, branch, full source SHA and resulting SHA where relevant;
- exact command/action or API operation (redact secrets);
- inputs, outputs, exit status and duration;
- artifact references and SHA-256 digests;
- decision, reason, reviewer and approval reference where applicable.

Required event types include: `task.opened`, `baseline.captured`, `inspection.completed`, `change.started`, `change.committed`, `test.started`, `test.completed`, `failure.observed`, `remediation.applied`, `verification.completed`, `review.completed`, `task.closed`.

Never rewrite a historical event to make the timeline look cleaner. Corrections are new events that reference the original event and explain the reason. Record clock source and measured clock offset for distributed/runtime evidence. If clock quality is unknown, state that limitation.

## 4. Forensic evidence and chain of custody

Preserve enough information for another competent reviewer to reproduce what happened and challenge the conclusion.

Minimum evidence bundle for a material engineering/security task:
- task contract and baseline snapshot;
- exact Git commit SHA(s), changed-path list and diff;
- test commands, tool/runtime versions, stdout/stderr and exit codes;
- CI run URL/ID and conclusion for the exact SHA;
- relevant deployment/runtime identifiers and health/SLI observations;
- SHA-256 manifest of evidence files;
- review/approval record and final decision.

Integrity rules:
1. Capture original evidence before remediation. Keep the original immutable; create a separate post-remediation bundle.
2. Hash each artifact with SHA-256 and record its size, media type, creation time, source and collector.
3. For multi-event evidence, use a canonical serialisation and a hash chain or Merkle root. Preserve the canonicalisation/version definition.
4. Sign evidence manifests with an authorised asymmetric key only when signing is actually configured. Record signer identity, key ID, algorithm and verification result. A hash is not a signature; a signature is not proof that the source data was truthful.
5. Verify signatures and recompute hashes after transfer and before relying on evidence.
6. Restrict access to raw logs and evidence by least privilege. Redact credentials, tokens, personal data and customer content without destroying the original in a controlled evidence store.
7. Retain evidence according to a documented retention policy. Record any collection gap, missing artifact or retention failure explicitly.

A forensic conclusion must separate direct observation, source-derived fact, inference and unverified hypothesis. Do not present an inference as an observed event.

## 5. Execution and verification gates

Use the narrowest safe scope and smallest meaningful change. Do not make unrelated edits during remediation.

Verification must match the claim:
- **Static:** syntax, formatting, schema validation, type checks and policy lint.
- **Unit:** deterministic tests for changed behavior and its edge cases.
- **Integration:** real boundary tests for identity, storage, network, queues, connectors and provider APIs where applicable.
- **Security:** secret scanning, dependency review, SAST, workflow permissions, threat-specific abuse cases and negative controls.
- **End-to-end:** complete user workflow from entry point to observable outcome.
- **Runtime:** live health, SLI/SLO, latency/error windows, stability and rollback checks in the target environment.
- **Evidence:** exact-SHA provenance, artifact digest and signature verification where the release claims require it.

A workflow file existing is not a successful workflow. A historical pass is not a pass on the current SHA. A skipped check is not a pass. A local simulation is not proof of production deployment. A client-reported assertion is not an independent platform assertion.

For a stability claim, define the observation window, probe interval, maximum tolerated gap, sample count and expected healthy state before testing. Test that a brief healthy response cannot satisfy a sustained-health assertion.

For an external or high-impact action, require a server-side approval record bound to the authenticated principal, target, action, payload digest and expiry. A model-supplied boolean such as `user_confirmed=true` is not an independent human approval.

## 6. Required critical self-review after every task

Before reporting completion, answer these questions against the evidence:

1. Did I deliver the requested outcome, or only describe/planning it?
2. Did I inspect the actual current state before modifying it?
3. Did I work on the intended repository, branch, commit and environment?
4. Did I miss any relevant file, integration, dependency, permission or acceptance criterion?
5. Do the tests exercise the real failure mode, or only a mock/happy path?
6. Are results from the exact resulting SHA and correct environment?
7. Are chronology, evidence hashes, signatures and custody sufficient for independent reconstruction?
8. Did I create any new security, privacy, availability, cost or operational risk?
9. Did I repeat a previously recorded failure pattern?
10. What remains unknown, blocked or dependent on a human or external system?

Score the task from 0 to 5 in each dimension:
- correctness;
- completeness;
- security and least privilege;
- verification quality;
- evidence and chronology;
- reproducibility and recovery;
- user outcome and operational value.

A score is not a substitute for gates. Any score below 4 requires a corrective action or an explicit reason why the gap is accepted. A critical security or data-integrity gate cannot be averaged away by high scores elsewhere.

## 7. Learning loop: prevent recurrence, not just describe it

Every material failure gets a record in a failure register:
- failure ID and first/last observed task IDs;
- symptom and impact;
- exact trigger and timeline;
- root cause, distinguishing trigger from systemic cause;
- why existing controls failed to prevent or detect it;
- corrective change;
- preventive control;
- regression test or monitoring rule;
- evidence that the regression test fails before the fix and passes after it;
- owner and due condition.

Before closing a new task, compare its failure modes with the register. If a known failure repeats, stop treating it as an isolated incident. Strengthen the shared process, template, automated check or guardrail.

Do not claim that a process has improved merely because a new document was written. Improvement requires a changed control and evidence that the control is effective.

## 8. Closure state machine

Allowed task states:

- `OPEN`: contract not yet accepted.
- `IN_PROGRESS`: changes or investigation are underway.
- `BLOCKED`: a required permission, decision, dependency or environment is unavailable.
- `FAILED`: acceptance criteria were not achieved.
- `PARTIAL`: some deliverables are verified, others remain open.
- `VERIFIED`: all technical acceptance criteria passed, but final owner/reviewer approval may still be required.
- `DONE`: verified, evidence preserved, self-review complete, and required approvals/hand-off completed.

Do not mark a Draft PR as merged, CI as green while checks are queued, a deployment as live without runtime evidence, or a product as production-ready based solely on repository content.

## 9. User-facing completion record

Every final task report must contain:
- outcome and task state;
- exact artifacts/links and commit/deployment references;
- what changed and what was not changed;
- tests/checks actually run and their exact results;
- critical self-review score and any corrective work completed;
- unresolved risks, unknowns and external dependencies;
- next decision only when it is genuinely required.

Lead with the result. Do not bury failures in a long description. Never claim background work, unobserved execution, or success without a tool result or reproducible evidence.

## 10. Default operating standard

For OLA and any high-trust engineering work, apply this protocol together with the repository security baseline and relevant threat model. Tailor the depth to risk, but never omit chronology, exact revision identity, evidence integrity, or truthful closure state for security-critical work.

This protocol is a control target. Its existence does not prove that every workflow, contributor or external service currently enforces it.
