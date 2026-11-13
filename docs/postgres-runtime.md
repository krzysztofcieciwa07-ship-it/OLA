# OLA PostgreSQL runtime — paid-order / evidence path

## Runtime selection

Set `OLA_DATABASE_URL` (preferred) or `DATABASE_URL` to a PostgreSQL DSN. Plain
`postgresql://` and legacy `postgres://` URLs are normalized to the SQLAlchemy
`postgresql+psycopg://` dialect. If neither variable is set, the application
keeps the existing SQLite path selected by `OLA_EG_DB_PATH`.

The runtime uses Psycopg 3. The driver is pinned in `requirements.txt`.

## Migration and roles

PostgreSQL DDL is intentionally not run by the API or worker at startup. Run
this once per deployment using a dedicated schema-owner/migration role:

```sh
export OLA_DATABASE_MIGRATION_URL='postgresql://migration_user:...@host:5432/ola'
export OLA_DATABASE_RUNTIME_ROLE='ola_runtime'
python scripts/migrate_postgres.py
```

The runtime role (default name `ola_runtime`) must exist before migration.
The migration script creates missing ORM tables, installs the evidence
append-only triggers, adds tenant ownership to Stripe event rows, installs
transaction-local row-level security (RLS) policies, and creates the narrowly
scoped `ola_authenticate_api_key(text)` SECURITY DEFINER lookup. It revokes
function execution from `PUBLIC` and grants it only to the configured
`OLA_DATABASE_RUNTIME_ROLE`. It records
`ola_tenant_rls_v4` in `ola_schema_migrations`. It is additive: it does not alter existing columns,
delete data, or copy records from the SQLite database. Do not point an existing
production tenant at the new database until a separately reviewed data-transfer
and reconciliation procedure has been run. Future column changes require a
new explicit migration.

The API and worker must use `OLA_DATABASE_URL` with a separate runtime role.
Grant only the required DML privileges. In particular, `evidence_records`
should grant `SELECT, INSERT` to the runtime role, not `UPDATE`, `DELETE` or `TRUNCATE`.
The application verifies required tables, triggers, RLS policies, scoped
authentication function, and runtime-role ownership/BYPASSRLS properties on
startup. It fails closed if any are missing. The migration role must not be
used as the runtime credential.

RLS is enabled for `tenants`, `api_keys`, `evidence_records`,
`stripe_events`, `checkout_orders`, `checkout_order_controls`,
`checkout_execution_jobs`, and `checkout_report_reviews`. A permissive base policy is combined with a restrictive tenant policy, so an
additional permissive policy cannot widen access. Tenant-owned rows are
visible only when the transaction-local `ola.tenant_id` setting matches
their `tenant_id` (or `tenants.id`). The API sets this context only after
API-key authentication; PostgreSQL authentication resolves the key through
`ola_authenticate_api_key(text)`, not a direct pre-auth table scan. Stripe
webhooks bind context only after signature verification and authoritative
Checkout Session lookup.

The tenant RLS policy does not grant a worker-wide bypass through
`ola.worker_mode`. A PostgreSQL custom GUC is transaction configuration, not
an independent security identity: any process holding the same database
credential can attempt to set it. The current worker code therefore remains
tenant-scoped after it resolves the job's tenant. A separate worker database
role, separate credentials, and a role-bound narrowly scoped policy/function
are required before the worker can perform cross-tenant outbox discovery.
Do not treat `OLA_EXECUTION_WORKER_TOKEN` plus a shared runtime DB credential
as a database privilege boundary. Legacy Stripe event rows without
`tenant_id` are intentionally invisible under RLS and require controlled
reconciliation; the migration does not infer tenant ownership from
untrusted event payloads.

Example minimum grants for the current payment/evidence tables (adapt the
role name and include other OLA tables when deploying the complete API):

```sql
GRANT USAGE ON SCHEMA public TO ola_runtime;
GRANT SELECT, INSERT ON tenants TO ola_runtime;
GRANT SELECT ON api_keys TO ola_runtime;
GRANT SELECT, INSERT ON evidence_records TO ola_runtime;
GRANT SELECT, INSERT, UPDATE ON stripe_events, checkout_orders,
    checkout_order_controls, checkout_execution_jobs TO ola_runtime;
GRANT SELECT ON ola_schema_migrations TO ola_runtime;
```

The migration grants `EXECUTE` on
`public.ola_authenticate_api_key(text)` to `ola_runtime` only. Do not grant
that function to `PUBLIC`; startup verification rejects a public execution
grant or a runtime role that cannot execute the function.

## Transaction policy

- Evidence sequence allocation is serialized per tenant with
  `pg_advisory_xact_lock(bigint)` held until transaction completion.
- Human Gate revalidates the evidence tip under the same tenant lock and locks
  the order/control rows with `SELECT ... FOR UPDATE`.
- Worker claims the outbox row with `SELECT ... FOR UPDATE`, then obtains the
  tenant chain lock before writing the `execution_started` evidence.
- Worker finalization locks the job row and tenant chain before recording the
  result. Stale `RUNNING` jobs are not auto-replayed; they enter
  `INTERRUPTED` and require manual reconciliation.
- SQLite continues to use `BEGIN IMMEDIATE`.

## Verification boundary

`tests/test_postgres_integration.py` uses a real isolated PostgreSQL schema and
checks least-privilege runtime access, concurrent evidence appends, sequence
continuity, hash-chain validity, rejection of evidence UPDATE/DELETE by the
append-only triggers, and startup rejection when UPDATE/DELETE/TRUNCATE are
granted to the runtime role. GitHub Actions runs that test against a PostgreSQL
service. A local SQLite test run is not a substitute for this PostgreSQL job.

This change does not by itself prove production failover, connection-pool
sizing, backup/restore, TLS enforcement, tenant-specific RLS, external LLM
execution, report review, or customer delivery. Those remain separate gates.
