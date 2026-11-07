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
python scripts/migrate_postgres.py
```

The migration script creates missing ORM tables, installs the two evidence
append-only triggers, and records the additive migration versions, including
`ola_human_identity_policy_v1`, in `ola_schema_migrations`. The persistent
`tenant_identity_policies` row stores the one-way tenant transition from
`LEGACY_API` to `OIDC_REQUIRED`; API startup verifies its table and migration
version but never performs PostgreSQL DDL. It is additive: it does not alter existing columns,
delete data, or copy records from the SQLite database. Do not point an existing
production tenant at the new database until a separately reviewed data-transfer
and reconciliation procedure has been run. Future column changes require a
new explicit migration.

The API and worker must use `OLA_DATABASE_URL` with a separate runtime role.
Grant only the required DML privileges. In particular, `evidence_records`
should grant `SELECT, INSERT` to the runtime role, not `UPDATE`, `DELETE` or `TRUNCATE`.
The application verifies required tables, the human identity policy migration
version and trigger presence on startup and fails closed if they are missing. The migration role must not be used as the
runtime credential.

Example minimum grants for the current payment/evidence tables (adapt the
role name and include other OLA tables when deploying the complete API):

```sql
GRANT USAGE ON SCHEMA public TO ola_runtime;
GRANT SELECT, INSERT ON tenants TO ola_runtime;
GRANT SELECT ON tenant_identity_policies TO ola_runtime;
GRANT SELECT ON api_keys TO ola_runtime;
GRANT SELECT, INSERT ON evidence_records TO ola_runtime;
GRANT SELECT, INSERT, UPDATE ON stripe_events, checkout_orders,
    checkout_order_controls, checkout_execution_jobs TO ola_runtime;
GRANT SELECT ON ola_schema_migrations TO ola_runtime;
```

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
