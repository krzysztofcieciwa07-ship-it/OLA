# P0 Writer Coverage Trace — API Evidence Submit & Atomic Writer

Date: 2026-11-20
Scope: source-code trace against repository default branch snapshot; no production database/log access.
Decision: Production GO remains NOT AUTHORIZED.

## 1. API evidence submit — `POST /evidence`

Source: `app/main.py:631-648`

Trace:
1. Request reaches `create_evidence`.
2. `tenant_from_key(x_api_key)` resolves tenant identity from API key.
3. `record_type` is validated as a nonempty string.
4. Privileged record types are rejected (`is_privileged_type`).
5. Payload must be a dict; reserved metadata keys are rejected.
6. Handler calls `append_evidence_atomic(tenant_id, record_type, payload, producer_id="tenant_api")`.

**Structural finding:** The public endpoint routes to the centralized atomic writer; it does not directly instantiate or insert `EvidenceRecord` in the handler.

## 2. Central atomic writer

Source: `app/database.py:345-376`

`append_evidence_atomic` opens `SessionLocal()`, calls `begin_write_transaction(db, tenant_id=tenant_id)`, calls `append_evidence_v4_locked(...)`, then commits. For deduplicated results it rolls back and returns the existing record metadata. Exception-path rollback/cleanup behavior is delegated to SQLAlchemy session/context lifecycle and still requires tests.

## 3. Lock implementation

Source: `app/database.py:37-65`

- SQLite: `BEGIN IMMEDIATE`; serializes database writes at SQLite level.
- PostgreSQL: requires non-empty tenant_id; obtains `pg_advisory_xact_lock` using tenant-specific lock key.
- Unsupported dialects fail closed.

Lock is transaction-scoped on PostgreSQL. Structural confirmation is not a runtime proof. Timeout behavior (including 500 ms policy and HTTP mapping) remains unverified.

## 4. Atomic writer usage inventory from code search

Found references in:
- `app/main.py`: public evidence endpoint and helper routes.
- `app/nina_execution.py`: wrapper/helper usage.
- `app/business_runtime.py`: internal business execution appends.
- `app/agent_runtime.py`: agent output evidence.
- `app/stripe_webhook.py`: Stripe event evidence.
- `app/paid_order_execution.py` and paid-order-related modules/tests: related execution evidence, with direct V4 primitive use in transaction contexts as identified separately.

This is a search-index-derived inventory and is not guaranteed exhaustive. Full repo-wide AST/grep scan and caller-level transaction trace are still required.

## 5. `atomic_legacy_writer` disposition

The function `append_evidence_atomic` is **not demonstrated to be dead or obsolete**. It is the current shared transactional wrapper and is referenced by multiple application modules. Decommissioning it now would be unsafe and counterproductive.

Recommended disposition: rename audit label from `atomic_legacy_writer` to `central_atomic_writer` (documentation only, not source rename yet). Preserve it as the canonical write boundary unless a migration design and tests prove otherwise.

## 6. Direct-write search findings

Code search found direct `EvidenceRecord(...)` construction and `db.add` in:
- `app/evidence_writer.py`: canonical V4 primitive, expected.
- `scripts/verify_readme_claims.py`: test/verification script fixture.
- `tests/test_evidence_writer_v4.py`: test fixture.

No other direct constructor match surfaced in the search results. This is not proof against raw SQL, dynamic writes, unindexed code, or infrastructure-level writers.

## 7. P0 status matrix

| Writer ID | Source | Transaction | Lock | Status |
|---|---|---|---|---|
| api_evidence_submit | `app/main.py:631-648` | Delegates to central wrapper | Tenant-scoped lock via wrapper | STRUCTURALLY TRACED; runtime OPEN |
| central_atomic_writer | `app/database.py:345-376` | Owns session/commit | `begin_write_transaction(tenant_id)` | STRUCTURALLY CONFIRMED; runtime OPEN |
| direct EvidenceRecord primitive | `app/evidence_writer.py` | Caller-owned | Caller-owned | CALLER AUDIT OPEN |
| script/test fixtures | scripts/tests | Non-production fixture paths | Not production writers | SCOPE REVIEW |

## 8. Remaining evidence required

- Exhaustive repo-wide search (including raw SQL, generated code, scripts and workflows).
- Caller-specific traces for all direct V4 primitive callers.
- Production logs/runtime telemetry to establish observed usage; no production logs were accessed.
- PostgreSQL integration tests for tenant lock, rollback, lock contention, timeout and error mapping.
- DB grants/roles, network/IAM, VPC/firewall and runtime-vs-migration role evidence.
- Queue/cron/worker inventory and deployment configuration.

## Audit conclusion

The `POST /evidence` endpoint structurally delegates to the centralized tenant-locked append wrapper. The wrapper is actively referenced by application components and should not be treated as a removable legacy path based on its name.

Writer Coverage is **IN PROGRESS / NOT PROVEN**. Production GO: **NOT AUTHORIZED**.
