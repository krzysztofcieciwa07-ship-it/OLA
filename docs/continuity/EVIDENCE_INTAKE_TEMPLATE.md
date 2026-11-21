# OLA di-OS — evidence intake template

Use one copy per evidence artifact or tightly coupled capture set. Attach the original export or immutable artifact where possible. Do not paste secrets, DSNs, tokens, private keys, customer data, payment card data, private messages or unredacted personal data into the repository, issue tracker or chat.

## A. Identification

- Evidence ID:
- Workstream / task ID:
- Related Issue / PR / release:
- Evidence title:
- Captured at (UTC, ISO 8601):
- Captured by (person or workload principal):
- Reviewed by (independent reviewer; state NONE if absent):
- Source system and account/project/resource ID:
- Environment: LOCAL / CI / STAGING / PRODUCTION / OTHER
- Source repository and exact commit SHA (if code-related):
- Deployment/service/resource IDs (if runtime-related):
- Tenant scope: REDACTED identifier or NOT APPLICABLE

## B. Claim being established

- Exact claim:
- Acceptance criterion:
- Positive path exercised:
- Negative path exercised:
- Expected result:
- Observed result:
- Status: OBSERVED / PARTIAL / BLOCKED / UNKNOWN / VERIFIED
- Why this artifact is relevant to the acceptance criterion:

## C. Capture method

- Command, API endpoint, dashboard path or SQL query (remove all credentials and secret literals):
- Tool / version:
- Identity and privilege scope used:
- Start time (UTC):
- End time (UTC):
- Query filters, pagination and result limits:
- Export completeness check (row count, page count, range, sampling plan):
- Redactions applied:
- Known blind spots (permissions, retention, sampling, missing pages, clock skew, unavailable logs):

## D. Integrity and provenance

- Original artifact URI:
- Artifact media type:
- Artifact size (bytes):
- SHA-256 of original bytes:
- Detached signature / attestation URI (or NONE):
- Signer / trust root / verification method:
- Verification command and version:
- Independent verification result:
- Recomputed digest:
- Exact source/environment binding result:
- Chain predecessor / event / run / operation ID, where applicable:

## E. Runtime / database correlation (when applicable)

- Service and deployment ID:
- Expected source SHA:
- Observed running source SHA:
- Database project/resource/branch identifier (never include DSN):
- Effective database role:
- Schema migration head:
- Relevant tenant/RLS/ACL state:
- Correlation keys (event_id, task_id, run_id, order_id, session_id, operation_id):
- DB commit/sequence/record identifiers:
- Log trace/request IDs:
- Time window and allowed clock skew:
- Record-to-log matching totals:
- Missing, duplicate, unmatched and out-of-window counts:
- Independent verifier and result:

## F. Security and operational impact

- Does this expose a credential or secret? YES / NO / UNKNOWN
- If YES: secret class only (never value), affected scope, first/last known exposure, revocation/rotation ticket and owner.
- Does it contain customer or personal data? YES / NO / UNKNOWN
- Redaction and retention approval:
- Does the result imply an external side effect? YES / NO
- Was explicit owner/operator authorization recorded? Reference only:
- Blast radius:
- Rollback / recovery evidence:
- Follow-up owner:
- Next required action:

## G. Closure decision

- Acceptance criterion met? YES / NO / PARTIAL
- Independent reviewer agrees? YES / NO / NOT REVIEWED
- Remaining blockers:
- Decision: ACCEPTED_AS_EVIDENCE / REJECTED / INSUFFICIENT / WAITING_EXTERNAL
- Decision timestamp (UTC):
- Decision owner:
- Supersedes evidence ID (if correcting a previous record):
- Task register updated at commit / issue / run:
- Limitations that must remain visible:

---

## Minimum acceptance rules

1. Evidence must be tied to an exact source SHA and intended environment/resource. A green job for another SHA is not transferable.
2. Include the capture method, UTC interval, result count/range and artifact digest. Screenshots without machine-readable identifiers are supporting material only.
3. Mark redacted or unavailable values as UNKNOWN; never reconstruct a secret or infer a database target from a variable name.
4. Separate code exists, tests pass, deployment is healthy, production data is durable, and an authorized human accepted the release. These are different claims.
5. Negative tests are required for identity, authorization, tenant isolation, replay, tamper and fail-closed boundaries where applicable.
6. A synthetic payment, mocked LLM, local deterministic runtime, staging rehearsal or source-level assertion cannot prove a live customer payment, external LLM execution or production deployment.
7. Keep historical evidence immutable. Corrections must link to the prior evidence ID and explain what changed.
8. VERIFIED requires reproducible independent verification. DONE in a task ledger requires every declared acceptance criterion to be met; documentation alone never closes a task.

## Owner hand-back summary

| Field | Owner response |
|---|---|
| Workstream / task ID | |
| Evidence ID(s) attached | |
| Environment and exact SHA/resource | |
| What is proven | |
| What remains unknown | |
| Who performed independent verification | |
| Next action and owner | |
| Expected completion criterion | |
