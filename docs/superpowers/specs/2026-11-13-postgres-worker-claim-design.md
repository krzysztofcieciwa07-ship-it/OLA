# PostgreSQL paid-order worker claim design

## Intent

Restore PostgreSQL paid-order outbox polling without giving the worker a tenant-wide RLS bypass or direct access to tenant-owned tables.

## Goals

- Give the worker a separate PostgreSQL login/credential from the API runtime role.
- Let that role claim only a bounded batch of jobs through one narrowly scoped SECURITY DEFINER function.
- Keep direct SELECT/INSERT/UPDATE/DELETE/TRUNCATE on `checkout_execution_jobs` denied to the worker role.
- Bind every dispatched execution to `job_id`, `tenant_id`, and an unpredictable, rotating claim token.
- Make claims atomic with `FOR UPDATE SKIP LOCKED` and finite leases so duplicate workers cannot receive the same live claim.
- Execute the job through the API runtime, which rechecks tenant RLS, claim token, payment evidence, Human Gate approval, and source provenance.

## Non-goals

- No BYPASSRLS worker role.
- No worker-wide custom GUC bypass.
- No shared API/worker database credential.
- No automatic replay of stale RUNNING jobs.
- No Neon migration, Railway environment changes, or production deployment in this code change.

## Approaches considered

1. **Shared runtime credential plus custom GUC** — rejected because any process holding that credential can set the GUC.
2. **Worker role with direct cross-tenant table access** — rejected because direct table privileges would expand the worker's blast radius.
3. **Separate worker role plus one SECURITY DEFINER claim function** — selected. The function returns only job ID, tenant ID, and claim token. The API performs tenant-scoped execution with its ordinary runtime role.

## Trust boundaries and flow

1. A migration administrator creates separate `ola_runtime` and `ola_worker` roles; neither is a superuser or BYPASSRLS role.
2. The migration installs `ola_claim_checkout_jobs(integer,integer)`, owned by the migration/schema owner, with `SECURITY DEFINER`, fixed `search_path = pg_catalog`, and schema-qualified table references.
3. PUBLIC and runtime-role EXECUTE are revoked. EXECUTE is granted only to the worker role. The worker role receives schema USAGE but no table privileges.
4. An external worker process connects using `OLA_DATABASE_WORKER_URL`, invokes the claim function, then sends `job_id`, `tenant_id`, and `claim_token` to the internal API over HTTPS with `OLA_EXECUTION_WORKER_TOKEN`.
5. The API establishes tenant context before opening its runtime DB transaction, verifies the row's current claim token, and performs the existing paid-order / Human Gate / evidence checks.
6. Claim tokens rotate on expired leases. Stale or ambiguous work is marked INTERRUPTED and requires manual reconciliation; it is never silently replayed.

## Required invariants

- Worker role is distinct from runtime role and cannot execute the API-key lookup function or access tenant tables directly.
- Claim function has a fixed search path, no PUBLIC EXECUTE, and no runtime-role EXECUTE.
- Every returned claim contains a random token bound to one job and tenant; expired tokens cease to match.
- A second poll cannot return an active lease.
- The API rejects missing, mismatched, or expired claims before running the task.
- All tenant-owned reads and writes remain under normal RLS tenant context.
- SQLite local worker behavior remains compatible.

## Verification

Real PostgreSQL 17 integration tests must prove role separation, ACLs, absence of direct worker table privileges, atomic claim behavior, lease expiry/rotation, and tenant-scoped API execution. A green SQLite worker test is not evidence for PostgreSQL worker security.

## Rollout boundary

Deployment requires separately provisioned worker credentials, HTTPS API endpoint configuration, reviewed Neon role grants/migration, and an independent Railway worker process. Code merge alone does not activate the PostgreSQL worker.
