# OLA PostgreSQL runtime — paid-order / evidence path

## Runtime selection

Set `OLA_DATABASE_URL` (preferred) or `DATABASE_URL` to a PostgreSQL DSN.
Plain `postgresql://` and legacy `postgres://` URLs are normalized to the
SQLAlchemy `postgresql+psycopg://` dialect. If neither variable is set, the
application keeps the existing SQLite path selected by `OLA_EG_DB_PATH`.

The runtime uses Psycopg 3. The driver is pinned in `requirements.txt`.

## Migration and database roles

PostgreSQL DDL is not run by the API or worker at startup. Apply it with a
dedicated schema-owner/migration credential. Provision distinct roles before
running the migration:

- `ola_runtime`: API database identity.
- `ola_worker`: outbox-claim identity only.
- Migration owner: owns the schema and SECURITY DEFINER functions; it must not
  be used by either runtime process.

Both application roles (`ola_runtime` and `ola_worker`) must be
`LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
NOREPLICATION`. Neither application role may be a member of another role,
and no untrusted principal may be granted either application role.

Neon automatically grants its project-admin principal (currently
`ola_migrator`, grantor `cloud_admin`) an administrative membership in
newly-created roles. The verifier permits only this exact provider-managed
edge to `ola_runtime` and `ola_worker`: `ADMIN TRUE INHERIT FALSE SET FALSE`.
That edge cannot be used to inherit or `SET ROLE` into application privileges,
but it does allow the provider-admin principal to delegate membership. Any
different member, grantor, or SET/INHERIT option is rejected. This is a narrow
Neon compatibility rule, not a general membership exception.

The provider-admin/migration principal currently inherits Neon’s
`neon_superuser` role and is therefore not a least-privilege application
identity. Its credential is highly privileged and must never be present in
API or worker runtime environments. Runtime startup fails closed if
`OLA_DATABASE_MIGRATION_URL` is non-empty. Run migrations only in a separate
one-off job, then rotate the migration credential and discard the job's
secret. A dedicated SQL-created schema-owner/migration-login pair remains the
preferred long-term replacement for using the provider-admin principal.

A Railway paid-order worker must use PostgreSQL for both its runtime connection
(`OLA_DATABASE_URL`) and isolated claim connection
(`OLA_DATABASE_WORKER_URL`). It must also have the API endpoint,
`OLA_EXECUTION_WORKER_TOKEN`, and the same `OLA_API_KEY_PEPPER` as the API
for V3 evidence verification. On Railway, SQLite fallback is rejected at
startup; a worker without the isolated claim URL or evidence pepper must not
start. The startup verifier also checks authenticated `session_user`,
table ownership, exact table grants and table ACL provenance, schema ACL
provenance (no PUBLIC/extra grantees or grant options), and function ACLs.
Do not rely on a custom GUC or application bearer token as a database
privilege boundary.

Example role provisioning (supply passwords using your secret-management
system, not source control):

```sql
CREATE ROLE ola_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS
    NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '<runtime-secret>';
CREATE ROLE ola_worker LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS
    NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '<worker-secret>';
```

Run the additive migration using a dedicated owner URL:

```sh
export OLA_DATABASE_MIGRATION_URL='postgresql://migration_user:...@host:5432/ola'
export OLA_DATABASE_RUNTIME_ROLE='ola_runtime'
export OLA_DATABASE_WORKER_ROLE='ola_worker'
python scripts/migrate_postgres.py
```

The migration creates missing ORM tables, installs the evidence append-only
triggers, adds tenant ownership to Stripe event rows, installs transaction-
local RLS, and creates the scoped `ola_authenticate_api_key(text)` and
role-bound `ola_claim_checkout_jobs(integer,integer)` functions. Both are
SECURITY DEFINER with a fixed `pg_catalog` search path. The auth
function must be owned by the `api_keys` table owner; the claim function
must be owned by the `checkout_execution_jobs` table owner. Those owners
are the dedicated migration/schema owner, never the runtime or worker role.
Do not enable `FORCE ROW LEVEL SECURITY` on these tables: it would subject
the owner-bound definer functions to tenant policies without a tenant
context. The auth function is executable only by the runtime role; the claim
function only by the worker role. The migration revokes schema CREATE from `PUBLIC`, grants the runtime role
its exact application DML matrix (SELECT/INSERT/UPDATE only on the tables it
uses, SELECT-only on `ola_schema_migrations`) and gives the worker only
schema USAGE plus claim-function EXECUTE—no direct table privileges,
including on `ola_schema_migrations`. The verifier checks these grants
exactly, including denial of PostgreSQL 17 `MAINTAIN`. Migration history
includes `ola_tenant_worker_claim_v5`.

The migration is additive with respect to the ORM baseline and does not copy
records from SQLite. It clears task text from the Stripe-event mirror after
moving it to the OLA order row. Do not point a production tenant at the new
database until a separately reviewed data-transfer and reconciliation
procedure has been run. Legacy Stripe event rows with `tenant_id IS NULL`
remain invisible under RLS; ownership is never inferred from untrusted event
payloads.

## API and worker runtime configuration

The API uses only the runtime credential:

```sh
OLA_DATABASE_URL='postgresql://ola_runtime:...@host:5432/ola'
```

The PostgreSQL paid-order worker uses a separate DSN and does not poll tables.
At startup it verifies that both authenticated `session_user` and effective
`current_user` equal `OLA_DATABASE_WORKER_ROLE` (a privileged DSN followed
by `SET ROLE` is rejected), and checks NOINHERIT/no-membership and role flags,
requires schema USAGE but no CREATE, rejects PUBLIC/extra schema ACLs and
grant options, verifies that the claim function is SECURITY DEFINER owned by
the separate migration role, and rejects any direct privileges on tenant-owned tables:

```sh
OLA_DATABASE_WORKER_URL='postgresql://ola_worker:...@host:5432/ola'
OLA_DATABASE_WORKER_ROLE='ola_worker'
OLA_DATABASE_RUNTIME_ROLE='ola_runtime'
OLA_EXECUTION_API_URL='https://ola-api.example'
OLA_EXECUTION_WORKER_TOKEN='<32-to-256-printable-ASCII-characters>'
OLA_EXECUTION_WORKER_STALE_SECONDS='900'
python scripts/run_paid_order_worker.py --once
```

For continuous polling, omit `--once`. The worker calls only
`ola_claim_checkout_jobs()` using `OLA_DATABASE_WORKER_URL`, then sends
the opaque claim coordinates to the API over HTTPS. Job ID is in the path;
tenant ID, claim token, worker token and lease duration are sent as headers,
never in query parameters. Redirects are rejected to prevent forwarding
credentials or claim tokens to another origin. API URLs with query strings,
fragments or embedded credentials are rejected.

The API verifies the worker token and database-issued claim before accepting
the request. PostgreSQL execution is acknowledged with HTTP 202 and scheduled
as a background task, rather than requiring the worker's HTTP request to stay
open for the duration of an agent run. The background executor opens a new
tenant-scoped transaction and rechecks the tenant, claim token and lease
before changing job state. SQLite continues to use the local worker path.

The claim lease is bounded to 60–86400 seconds (default 900) and the same
value is passed from the worker to the API and executor. An expired lease may
be re-issued only for a never-started `QUEUED` job (`attempt_count = 0`).
A job in `RUNNING` is never automatically reclaimed or replayed: the API
background task is process-local, and without a heartbeat plus a reliable
cancellation/fencing protocol the system cannot prove that an expired worker
is dead rather than merely slow. A crashed or disconnected RUNNING job stays
blocked for manual reconciliation after an operator independently confirms
that no executor is still active. There is no heartbeat/lease renewal yet.
A worker/API process restart after HTTP 202 does not transfer task state to
another process automatically; the job remains visible for audit and must be
reconciled manually rather than automatically re-executed.

## Tenant RLS and least privilege

RLS is enabled for `tenants`, `api_keys`, `evidence_records`,
`stripe_events`, `checkout_orders`, `checkout_order_controls`,
`checkout_execution_jobs` and `checkout_report_reviews`. A permissive base
policy is combined with a restrictive tenant policy, so an additional
permissive policy cannot widen access. Every restrictive policy resolves the
tenant through the SECURITY DEFINER function
`ola_current_tenant_id()`; it does not trust `ola.tenant_id` by itself.

### Signed tenant-context trust boundary

The API sets a transaction-local tenant ID and HMAC-SHA-256 signature only
after API-key authentication or another trusted internal authorization step.
The signed message is domain-separated as
`OLA-TENANT-CONTEXT-V1:<tenant_id>`. The verifier reads its active key from
`ola_rls_context_secrets`, a migration-owned table with no direct runtime,
worker or PUBLIC privileges. It uses PostgreSQL's built-in SHA-256 primitive;
no extension is required. Runtime startup independently proves that the
configured secret matches the database verifier.

A process holding only the `ola_runtime` database login can set arbitrary
custom GUC values, including `ola.tenant_id`, but cannot forge the matching
signature or read the verification key. A valid signature for one tenant
cannot be replayed for another tenant. Missing, malformed or invalid context
fails closed and exposes no tenant rows.

`OLA_RLS_CONTEXT_SECRET` must contain at least 32 bytes and must be supplied
to the one-off migration job and API runtime process. The isolated claim
worker does not receive this secret because it has no direct tenant-table access. It is a
high-value application secret: never expose it to clients, logs, support
bundles or untrusted SQL users. A compromised trusted application process
that can read this secret remains outside this database-credential-only
containment guarantee. Key rotation requires a versioned key-ring migration;
do not rotate the active value ad hoc.

The `ola.worker_mode` custom GUC does not bypass RLS. The worker's
cross-tenant discovery remains isolated in the SECURITY DEFINER claim
function, protected by database role ACLs; the worker gets no direct SELECT,
INSERT, UPDATE, DELETE or TRUNCATE on tenant-owned tables. Stripe webhook
context is established only after signature verification and authoritative
Checkout Session lookup.

## Hash-chain digest rationale

New evidence records use V3 HMAC-SHA-256 over a domain-separated canonical
record. The HMAC key is derived with a dedicated context string from the
server-side `OLA_API_KEY_PEPPER`; the pepper must contain at least 32 bytes
and must be identical across all API replicas and independent verifiers.
This prevents a database-only reader from testing guessed payload values
against published record digests and prevents a database-only writer from
recomputing valid V3 links without the server secret.

V1 and V2 records remain readable for historical integrity verification only;
new writes must never use their unkeyed SHA-256 functions. Historical V1/V2
verification does not retroactively provide confidentiality or keyed
authenticity. The independent runtime, staging and invoice verifiers implement
the V3 calculation separately and fail closed when the pepper is absent.
The chain is still not a third-party signature or proof against compromise of
the trusted application process or its secret. The current V3 implementation
uses one active root pepper: rotating `OLA_API_KEY_PEPPER` without first
introducing a versioned evidence-key ring would invalidate historical V3
verification. Do not rotate that pepper until a key-ring migration is designed
and tested. API-key fingerprints continue to use a separate bounded scrypt
path with the configured pepper. Passwords and other low-entropy credentials
require a deliberately slow KDF.

## Transaction policy

- Evidence sequence allocation is serialized per tenant with
  `pg_advisory_xact_lock(bigint)` held until transaction completion.
- Human Gate revalidates the evidence tip under the same tenant lock and locks
  the order/control rows with `SELECT ... FOR UPDATE`.
- Worker claims use `FOR UPDATE SKIP LOCKED` inside the role-bound claim
  function, then the tenant-scoped API locks the job row and evidence chain
  before execution.
- Finalization locks the job row and tenant chain, and rejects a lost or
  expired claim token. Stale RUNNING jobs require manual reconciliation.
- SQLite continues to use `BEGIN IMMEDIATE`.

## Verification boundary

`tests/test_postgres_integration.py` uses a real isolated PostgreSQL schema
and checks least-privilege runtime/worker roles, tenant read/write isolation,
claim-function ACLs and lease behavior, concurrent evidence appends, sequence
continuity, hash-chain validity, evidence UPDATE/DELETE rejection and startup
rejection of policy or role tampering. GitHub Actions runs these tests against
a PostgreSQL service. A local SQLite test run is not a substitute.

This change does not by itself prove production failover, connection-pool
sizing, backup/restore, TLS enforcement, tenant-specific RLS, external LLM
execution, report review or customer delivery. Neon/Railway migration and
deployment remain separate controlled steps.
