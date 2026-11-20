# P0 Rogue Writer Hunt — Evidence Records
Date: 2026-11-20
Repository: krzysztofcieciwa07-ship-it/OLA
Search snapshot/base: main at 8adf30cd5e41a18a5345f66e67f5ddcdbc164862

## Scope and limitations
Repository code-search and source inspection only; not runtime or production telemetry. Search is not exhaustive (index coverage, dynamic SQL, generated code, external DB clients, deployed code drift, and effective production privileges remain unverified).

## Findings

### Canonical persistence primitive
- `app/evidence_writer.py`: `append_evidence_v4_locked(db, tenant_id, ...)` is the lower-level persistence primitive and expects caller-established tenant-chain transaction lock.
- `app/database.py`: `append_evidence_atomic(...)` calls `begin_write_transaction(db, tenant_id=...)`, delegates to the locked primitive and commits/rolls back.
- The only direct `EvidenceRecord(...)` constructor surfaced by code search in application source was in `app/evidence_writer.py`; other constructor hits were fixtures/tests. This is a bounded search finding.

### Direct lower-level callers identified
| Caller | Write path | Lock / transaction signal | Audit status |
|---|---|---|---|
| `app/nina_workflow_gate.py` | direct primitive for workflow/candidate approval | Both functions call `begin_write_transaction`, re-read tip, append, commit | STRUCTURAL PASS; exception/runtime tests pending |
| `app/order_approval.py` | direct primitive for paid-order approval | `begin_write_transaction`, locked validation, append and related DB updates | STRUCTURAL PASS; tests pending |
| `app/report_review.py` | `_append_locked` helper delegates to primitive | Transaction path requires dedicated source review | OPEN |
| `app/paid_order_execution.py` | helper delegates to primitive | Imports transaction/lock helpers; full paths and exception boundaries require review | OPEN |
| `app/database.py` | central wrapper | Initializes transaction then delegates | STRUCTURAL PASS |

Direct lower-level callers are not rogue bypasses solely because they avoid `append_evidence_atomic`; each must prove lock-before-chain-validation, revalidation under lock, transaction/commit/rollback, and tenant scope.

### Raw SQL and operational scripts
Search surfaced raw evidence table inserts/updates in test/verification/operational contexts:
- `.github/workflows/nina-igor-ollama.yml`: direct SQL INSERT into `evidence_records` in workflow fixture/import context; verify environment isolation and DB target.
- `tests/test_staging_verify.py`: direct fixture INSERT and deliberate UPDATE/tamper test.
- `scripts/staging_verify.py`, `scripts/verify_readme_claims.py`, `scripts/verify_business_invoice.py`, `scripts/verify_agent_runtime.py`: direct SQL or tamper/verification operations surfaced; classify DB targets and purpose.
- `workstation/OLA-Workstation.ps1`: bootstrap SQL creates tenant/API-key records; evidence table is read/tamper-tested in local verification. No evidence-record creation was identified in the returned excerpt.

These are not automatically production rogue writers. Operational scripts must be classified by environment, credential, invocation and production reachability.

### DB privilege / append-only controls
Search surfaced `docs/postgres-runtime.md` granting runtime role SELECT/INSERT (not UPDATE/DELETE) on `evidence_records`; append-only trigger and validation code surfaced in `app/database.py` and `app/main.py`. Structural only: deployed grants, trigger definitions, ownership and actual runtime connection identity remain unverified.

## Search patterns
`append_evidence_v4_locked`, `append_evidence_atomic`, `EvidenceRecord`, `EvidenceRecord(`, `evidence_records INSERT`, `evidence_records SET`, `exec_driver_sql evidence_records`, `db.add(`.

## Priority follow-up
1. Inspect `report_review.py` and `paid_order_execution.py` end-to-end; prove lock-before-validation and commit/rollback on each evidence append.
2. Enumerate raw SQL evidence writes across workflows, shell/PowerShell, migrations and scripts; classify target DB, credentials, invocation and environment.
3. Verify effective runtime DB grants/trigger definitions and identify principals with INSERT or mutation privileges.
4. Correlate production records with wrapper/caller telemetry; no production logs or DB count reconciliation performed.
5. Concurrency/timeout tests remain separate P1 gate.

## Status
- Central writer structurally identified: PASS (structural).
- Direct lower-level caller inventory: PARTIAL.
- Raw SQL/script path inventory: PARTIAL.
- Production telemetry: NOT VERIFIED.
- Writer coverage: IN PROGRESS.
- Production GO: NOT AUTHORIZED.
