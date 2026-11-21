# P0 Credential Isolation & Migration Writer Review (source-only)
Date: 2026-11-20
Repository: krzysztofcieciwa07-ship-it/OLA
Reviewed default-branch source snapshot during audit.

## 1. Credential isolation — evidence and gaps

### Repository evidence
- `docs/postgres-runtime.md` documents distinct `OLA_DATABASE_MIGRATION_URL` and runtime `OLA_DATABASE_URL`, separate migration/runtime roles, and says runtime role must not be used as migration credential.
- The documented runtime grants give `SELECT, INSERT` to `evidence_records`, not UPDATE/DELETE/TRUNCATE.
- `scripts/migrate_postgres.py` requires `OLA_DATABASE_MIGRATION_URL`, validates the PostgreSQL Psycopg dialect and invokes schema migration; it is an explicit CLI, not automatic API startup DDL.
- `app/database.py` runtime schema verification checks tables/columns, migration version, append-only triggers, and checks runtime role lacks UPDATE/DELETE/TRUNCATE on evidence_records.
- `.github/workflows/paid-order-postgres.yml` uses an isolated local CI PostgreSQL service with test-only credentials; workflow grants contents:read and checks out exact SHA with `persist-credentials: false`.
- `SECURITY.md` and `.github/SECURITY-BASELINE.md` state production secrets must not be committed, recommend short-lived CI credentials, and require least privilege. The baseline explicitly notes several account-level settings remain unverified.

### Not proven
- Actual production secret manager, IAM principal/role bindings, secret scopes and rotation.
- Effective production DB grants and current DB role identity.
- Firewall/VPC/security-group rules, TLS enforcement and network reachability.
- CI and workstation environment-variable/secret scopes in the live GitHub/account/deployment configuration.
- Whether any developer/workstation identity can access production DB.
- Runtime credentials are not shown in source search as hardcoded production secrets, but absence from search does not prove they are absent from secret stores, deployment config, or logs.

## 2. Workstation and CI isolation
- `.github/workflows/paid-order-postgres.yml` explicitly targets a local ephemeral test Postgres service (`localhost:5432/ola_test`) with test-only credentials in the workflow definition.
- `.github/workflows/nina-igor-ollama.yml` creates and uses a Docker-local SQLite evidence source, exports tenant-scoped evidence into a temporary SQLite target for independent verification, and uploads artifacts. No production DB DSN was surfaced in inspected excerpts; full secret/environment audit remains open.
- `workstation/OLA-Workstation.ps1` uses a local Docker container and `/data/ola.db` for workstation evidence/bootstrap in the excerpt previously inspected. Actual workstation credential and network controls are not observable from repository source.
- Therefore CI/workstation isolation is DESIGN-DOCUMENTED / SOURCE-SIGNAL, not CONFIGURATION-VERIFIED.

## 3. Migration and schema writer review
- `scripts/migrate_postgres.py` is the explicit PostgreSQL schema migration entrypoint and requires `OLA_DATABASE_MIGRATION_URL`.
- `app/database.py:migrate_postgres_schema` creates migration metadata, creates ORM tables, applies additive column updates, moves/clears legacy task data, installs evidence append-only triggers, and records migration versions.
- `create_postgres_append_only_triggers` obtains a PostgreSQL advisory transaction lock keyed to `__ola_schema_migration__` and recreates UPDATE/DELETE evidence triggers.
- This is a schema migration lock signal. It is not evidence of exclusive/sole authorization: DB ownership, privilege separation, migration job permissions, network controls, audit logging, and concurrent deployment controls are not verified.
- Repository search for `alembic evidence_records` returned no results. That does not establish absence of other migration tools or raw migration paths.
- Migration operations are structurally capable of altering schema and some legacy data; operational authorization and backup/reconciliation protections need independent review.

## 4. Production telemetry correlation
No production DB, runtime logs, or telemetry stream was available in this source-only audit. Record-count/log correlation and 100-record sampling were not performed.
A valid correlation design should use stable append-event identifiers and producer/source commit plus tenant, record ID, sequence and hash; avoid count-only comparison because retries, deduplication, retention, sampling and log loss can skew counts.

## Status
- Credential source separation: DOCUMENTED; CONFIGURATION UNVERIFIED.
- CI test DB isolation: SOURCE-CONFIRMED for inspected workflow.
- Workstation DB isolation: SOURCE SIGNAL; live access unverified.
- Migration entrypoint: SOURCE-CONFIRMED.
- Migration schema-lock: STRUCTURAL SIGNAL, not authorization proof.
- Effective production IAM/network/DB privileges: OPEN.
- Production telemetry correlation: NOT AVAILABLE.
- Writer coverage: IN PROGRESS.
- Production GO: NOT AUTHORIZED.
