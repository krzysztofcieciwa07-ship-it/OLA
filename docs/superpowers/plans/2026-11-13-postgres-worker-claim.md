# PostgreSQL Paid-Order Worker Claim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Restore PostgreSQL paid-order queue polling without granting the worker direct access to tenant-owned tables or a tenant-wide RLS bypass.

**Architecture:** A separate PostgreSQL worker role can execute one SECURITY DEFINER claim function that atomically issues bounded, expiring job leases. The external worker sends the job ID, tenant ID, and claim token to the authenticated internal API; the API executes under normal tenant RLS and validates the persisted claim.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Psycopg 3, PostgreSQL 17, FastAPI, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-13-postgres-worker-claim-design.md`

## Global Constraints

- No PostgreSQL custom-GUC bypass and no role with `BYPASSRLS`.
- Worker role has schema USAGE and function EXECUTE only; no direct tenant-table DML.
- Claim function is SECURITY DEFINER, fixed `search_path = pg_catalog`, schema-qualified, not executable by PUBLIC or runtime role.
- Leases are bounded, random, rotated on expiry, and validated by the runtime API.
- Stale RUNNING work is interrupted for manual reconciliation; it is never auto-replayed.
- SQLite worker behavior remains backward compatible.
- No Neon migration, Railway environment changes, merge, or deployment in this implementation.

## Review Focus

- Missing, malformed, expired, replayed, or cross-tenant claim tokens must be rejected before execution.
- A concurrent poll must not receive a live lease already held by another worker.
- Stale QUEUED leases can be reclaimed with a new token; stale RUNNING jobs must become INTERRUPTED, not execute again.
- The worker role must not inherit runtime privileges or own tenant tables.
- Missing/partial patch artifacts or role metadata must fail closed rather than report a clean security gate.

---

### Task 1: PostgreSQL role-bound claim capability

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py`
- Modify: `scripts/migrate_postgres.py`
- Modify: `tests/test_postgres_integration.py`

**Interfaces:**
- Migration accepts both `runtime_role` and `worker_role`.
- Adds `CheckoutExecutionJob.claimed_at: Integer | None`.
- Creates `ola_claim_checkout_jobs(integer, integer)`, returning `job_id, tenant_id, claim_token`.
- Worker role receives EXECUTE on the function, but no direct privileges on protected tables.

- [ ] Keep the new integration test as RED until the missing column/function/ACL/lease contract is implemented.
- [ ] Add an additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS claimed_at INTEGER` migration.
- [ ] Implement the bounded SECURITY DEFINER claim function using `FOR UPDATE SKIP LOCKED`, random token rotation, and finite lease timestamps.
- [ ] Grant function EXECUTE only to the configured worker role; revoke PUBLIC and runtime access.
- [ ] Extend startup verification to validate worker role existence, role flags, function owner/config/ACL, and lack of direct table privileges.
- [ ] Pass both role names through the migration CLI and isolated test fixture.
- [ ] Run the real PostgreSQL 17 contract until the new RED test becomes GREEN.

### Task 2: Tenant-bound runtime execution

**Files:**
- Modify: `app/paid_order_execution.py`
- Modify: `app/main.py`
- Modify: `tests/test_paid_order_execution.py`
- Modify: `tests/test_postgres_integration.py`

**Interfaces:**
- PostgreSQL execution accepts `job_id`, `tenant_id`, and `claim_token`.
- The runtime API sets tenant context before any ORM query.
- The job lookup is constrained by ID and tenant; the persisted token must match before state changes.

- [ ] Add a failing test for a missing or mismatched PostgreSQL claim.
- [ ] Add a failing test for an expired lease and a stale RUNNING job.
- [ ] Implement constant-time claim comparison and tenant-scoped row lookup.
- [ ] Preserve SQLite’s existing in-process worker interface.
- [ ] Ensure finalization verifies the same claim token and tenant before writing.
- [ ] Verify the task remains at-most-once and stale RUNNING work is INTERRUPTED without invoking NINA.

### Task 3: Separate PostgreSQL worker process

**Files:**
- Modify: `scripts/run_paid_order_worker.py`
- Modify: `tests/test_paid_order_execution.py`
- Modify: `docs/postgres-runtime.md`

**Interfaces:**
- `OLA_DATABASE_WORKER_URL`: separate database login for the worker.
- `OLA_EXECUTION_API_URL`: internal API HTTPS endpoint.
- `OLA_EXECUTION_WORKER_TOKEN`: existing strong worker API credential.
- The worker claims via SQL function and dispatches only `job_id`, `tenant_id`, and `claim_token`.

- [ ] Add focused tests for missing worker DSN, missing API URL, non-HTTPS remote endpoint, and claim dispatch errors.
- [ ] Implement a worker SQLAlchemy engine using only the worker DSN.
- [ ] Implement claim polling via the SECURITY DEFINER function; no direct ORM SELECT on the queue.
- [ ] Dispatch claims to the internal API over HTTPS with the worker token and claim headers.
- [ ] Keep SQLite mode and current tests unchanged.
- [ ] Verify worker loop exit codes and failure handling.

### Task 4: Documentation and end-to-end evidence

**Files:**
- Modify: `docs/postgres-runtime.md`
- Modify: `docs/superpowers/specs/2026-11-13-postgres-worker-claim-design.md`
- Modify: `.github/workflows/paid-order-postgres.yml` only if a required test path is currently omitted.

- [ ] Document runtime and worker roles, secret variables, function grants, lease semantics, and manual reconciliation.
- [ ] Run the focused PostgreSQL 17 tests.
- [ ] Run Python package CI and the full required workflow matrix on the exact final SHA.
- [ ] Confirm no CodeQL HIGH/CRITICAL in newly added/changed lines; retain the repository-wide alert inventory.
- [ ] Keep the PR Draft until all code checks pass and the worker is validated end-to-end.
- [ ] Do not run staging migration, merge, or deploy in this plan.
