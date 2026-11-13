import hashlib
import os
import re
import uuid

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session as OrmSession, declarative_base, sessionmaker

from .tenant_context import current_tenant_id, worker_mode_enabled


def database_url_from_env(environ=None):
    """Resolve the runtime URL while preserving the existing SQLite default."""
    env = os.environ if environ is None else environ
    configured = env.get("OLA_DATABASE_URL") or env.get("DATABASE_URL")
    if not configured:
        db_path = env.get("OLA_EG_DB_PATH", "ola.db")
        return f"sqlite:///{db_path}"

    url = configured.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith(("postgresql+psycopg://", "sqlite:")):
        return url
    raise ValueError("OLA_DATABASE_URL must use PostgreSQL/psycopg or SQLite")


def tenant_advisory_lock_key(tenant_id):
    """Return a stable signed bigint for PostgreSQL's transaction advisory lock."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required for an evidence-chain lock")
    raw = hashlib.sha256(b"ola:evidence-chain:v1:" + tenant_id.encode("utf-8")).digest()[:8]
    value = int.from_bytes(raw, byteorder="big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


def lock_tenant_evidence_chain(db, tenant_id):
    """Serialize a tenant's evidence chain inside the current transaction."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        # BEGIN IMMEDIATE already serializes SQLite writers process-wide.
        return
    if dialect == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": tenant_advisory_lock_key(tenant_id)},
        )
        return
    raise RuntimeError(f"no evidence-chain lock policy for database dialect: {dialect}")


def begin_write_transaction(db, tenant_id=None):
    """Begin a serialized write transaction for the selected backend."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if tenant_id is not None:
            lock_tenant_evidence_chain(db, tenant_id)
        return
    if dialect == "postgresql":
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required for a PostgreSQL write transaction")
        lock_tenant_evidence_chain(db, tenant_id)
        return
    raise RuntimeError(f"no atomic write policy for database dialect: {dialect}")


DB_PATH = os.getenv("OLA_EG_DB_PATH", "ola.db")  # legacy SQLite tooling compatibility
DB_URL = database_url_from_env()
if DB_URL.startswith("sqlite:"):
    engine = create_engine(
        DB_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
elif DB_URL.startswith("postgresql+psycopg://"):
    engine = create_engine(DB_URL, pool_pre_ping=True, isolation_level="READ COMMITTED")
else:  # pragma: no cover - guarded by database_url_from_env
    raise RuntimeError("unsupported database URL")

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


@event.listens_for(OrmSession, "after_begin")
def _apply_postgres_tenant_context(session, transaction, connection):
    """Overwrite transaction-local RLS context on every PostgreSQL transaction."""
    if connection.dialect.name != "postgresql":
        return
    tenant_id = current_tenant_id()
    connection.execute(
        text("SELECT set_config('ola.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id or ""},
    )
    connection.execute(
        text("SELECT set_config('ola.worker_mode', :worker_mode, true)"),
        {"worker_mode": "on" if worker_mode_enabled() else "off"},
    )


def create_postgres_append_only_triggers(connection):
    """Install PostgreSQL evidence immutability triggers using a migration role."""
    schema_lock = tenant_advisory_lock_key("__ola_schema_migration__")
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": schema_lock},
    )
    connection.exec_driver_sql("""
    CREATE OR REPLACE FUNCTION ola_reject_evidence_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $ola$
    BEGIN
        RAISE EXCEPTION 'evidence_records is append-only' USING ERRCODE = '55000';
    END;
    $ola$;
    """)
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS evidence_no_update ON evidence_records"
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS evidence_no_delete ON evidence_records"
    )
    connection.exec_driver_sql("""
    CREATE TRIGGER evidence_no_update
    BEFORE UPDATE ON evidence_records
    FOR EACH ROW EXECUTE FUNCTION ola_reject_evidence_mutation()
    """)
    connection.exec_driver_sql("""
    CREATE TRIGGER evidence_no_delete
    BEFORE DELETE ON evidence_records
    FOR EACH ROW EXECUTE FUNCTION ola_reject_evidence_mutation()
    """)


def install_append_only_triggers(bind=None):
    """Create SQLite triggers; on PostgreSQL verify migration-installed triggers."""
    target = bind or engine
    if target.dialect.name == "sqlite":
        with target.begin() as conn:
            conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS evidence_no_update
            BEFORE UPDATE ON evidence_records
            BEGIN SELECT RAISE(ABORT, 'evidence_records is append-only'); END;
            """)
            conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS evidence_no_delete
            BEFORE DELETE ON evidence_records
            BEGIN SELECT RAISE(ABORT, 'evidence_records is append-only'); END;
            """)
        return
    if target.dialect.name == "postgresql":
        verify_postgres_schema(target)
        return
    raise RuntimeError(f"no append-only trigger policy for database dialect: {target.dialect.name}")


def verify_postgres_schema(bind, *, enforce_runtime_privileges=True, runtime_role=None, worker_role=None):
    """Fail closed unless runtime RLS and the isolated worker claim boundary are present."""
    runtime_role = runtime_role or os.getenv("OLA_DATABASE_RUNTIME_ROLE", "ola_runtime").strip()
    worker_role = worker_role or os.getenv("OLA_DATABASE_WORKER_ROLE", "ola_worker").strip()
    role_pattern = r"[A-Za-z_][A-Za-z0-9_$]{0,62}"
    if not isinstance(runtime_role, str) or re.fullmatch(role_pattern, runtime_role) is None:
        raise RuntimeError("configured PostgreSQL runtime role is invalid")
    if not isinstance(worker_role, str) or re.fullmatch(role_pattern, worker_role) is None:
        raise RuntimeError("configured PostgreSQL worker role is invalid")
    if worker_role == runtime_role:
        raise RuntimeError("PostgreSQL worker role must be distinct from runtime role")
    required_columns = {
        "tenants": {"id", "name"},
        "api_keys": {"id", "tenant_id", "key_hash", "role"},
        "evidence_records": {
            "id", "tenant_id", "seq", "record_type", "payload_json",
            "prev_hash", "record_hash",
        },
        "stripe_events": {"id", "tenant_id", "event_id", "status", "run_id", "task", "result_json"},
        "checkout_orders": {
            "id", "tenant_id", "idempotency_key_hash", "request_hash", "task", "status",
            "created_at", "stripe_session_id", "checkout_url", "payment_event_id",
            "payment_result_json",
        },
        "checkout_order_controls": {
            "id", "order_id", "tenant_id", "requester_id", "status",
            "payment_evidence_id", "approver_id", "approval_reason", "approved_tip_hash",
            "approval_record_hash", "created_at", "approved_at",
        },
        "checkout_execution_jobs": {
            "id", "tenant_id", "order_id", "approval_record_hash", "task", "status",
            "attempt_count", "claim_token", "claimed_at", "started_at", "finished_at", "run_id",
            "result_json", "error_code", "created_at",
        },
        "checkout_report_reviews": {
            "id", "order_id", "tenant_id", "reviewer_id", "status", "report_sha256",
            "reviewed_tip_hash", "reason", "approval_evidence_id", "reviewed_at",
            "delivery_evidence_id", "delivered_at",
        },
        "ola_schema_migrations": {"version", "description", "applied_at"},
    }
    inspector = inspect(bind)
    missing = sorted(name for name in required_columns if not inspector.has_table(name))
    if missing:
        raise RuntimeError("PostgreSQL schema is not migrated; missing tables: " + ", ".join(missing))
    for table_name, expected in required_columns.items():
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        absent = sorted(expected - actual)
        if absent:
            raise RuntimeError(
                f"PostgreSQL table {table_name} is missing required columns: " + ", ".join(absent)
            )

    expected_unique_constraints = {
        "api_keys": {("key_hash",)},
        "evidence_records": {("tenant_id", "seq")},
        "stripe_events": {("event_id",)},
        "checkout_orders": {
            ("tenant_id", "idempotency_key_hash"),
            ("stripe_session_id",),
            ("payment_event_id",),
        },
        "checkout_order_controls": {("order_id",)},
        "checkout_execution_jobs": {("order_id",)},
    }
    for table_name, expected in expected_unique_constraints.items():
        actual = {
            tuple(item.get("column_names") or ())
            for item in inspector.get_unique_constraints(table_name)
        }
        # SQLAlchemy models some single-column unique fields as unique indexes.
        actual.update(
            tuple(item.get("column_names") or ())
            for item in inspector.get_indexes(table_name)
            if item.get("unique")
        )
        if not expected.issubset(actual):
            raise RuntimeError(f"PostgreSQL table {table_name} is missing required unique constraints/indexes")

    with bind.connect() as conn:
        applied = conn.execute(text(
            "SELECT 1 FROM ola_schema_migrations WHERE version = :version"
        ), {"version": "ola_tenant_rls_v4"}).first()
        worker_claim_migration = conn.execute(text(
            "SELECT 1 FROM ola_schema_migrations WHERE version = :version"
        ), {"version": "ola_tenant_worker_claim_v5"}).first()
        trigger_rows = conn.execute(text("""
            SELECT t.tgname, pg_get_triggerdef(t.oid), p.proname,
                   pg_get_functiondef(p.oid)
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            JOIN pg_proc AS p ON p.oid = t.tgfoid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE c.relname = 'evidence_records'
              AND n.nspname = current_schema()
              AND NOT t.tgisinternal
        """)).all()
        if enforce_runtime_privileges:
            evidence_privileges = conn.execute(text("""
                SELECT has_table_privilege(current_user, 'evidence_records', 'UPDATE'),
                       has_table_privilege(current_user, 'evidence_records', 'DELETE'),
                       has_table_privilege(current_user, 'evidence_records', 'TRUNCATE')
            """)).one()
        else:
            evidence_privileges = (False, False)
        rls_tables = (
            "tenants", "api_keys", "evidence_records", "stripe_events",
            "checkout_orders", "checkout_order_controls",
            "checkout_execution_jobs", "checkout_report_reviews",
        )
        rls_rows = conn.execute(text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   pg_get_userbyid(c.relowner)
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = ANY(:table_names)
        """), {"table_names": list(rls_tables)}).all()
        policy_rows = conn.execute(text("""
            SELECT tablename, policyname, cmd, permissive, roles,
                   qual, with_check
            FROM pg_policies
            WHERE schemaname = current_schema()
              AND tablename = ANY(:table_names)
        """), {"table_names": list(rls_tables)}).all()
        auth_function = conn.execute(text("""
            SELECT p.oid, p.prosecdef, p.proconfig,
                   EXISTS (
                       SELECT 1
                       FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
                       WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                   ) AS public_execute,
                   has_function_privilege(current_user, p.oid, 'EXECUTE') AS runtime_execute,
                   has_function_privilege(:worker_role, p.oid, 'EXECUTE') AS worker_execute,
                   (
                       SELECT array_agg(DISTINCT pg_get_userbyid(acl.grantee))
                       FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
                       WHERE acl.privilege_type = 'EXECUTE'
                         AND acl.grantee <> 0
                         AND acl.grantee <> p.proowner
                         AND pg_get_userbyid(acl.grantee) <> current_user
                   ) AS extra_execute_grantees,
                   EXISTS (
                       SELECT 1
                       FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
                       WHERE acl.privilege_type = 'EXECUTE'
                         AND acl.grantee <> p.proowner
                         AND acl.is_grantable
                   ) AS execute_grant_option,
                   pg_get_userbyid(p.proowner) AS owner
            FROM pg_proc AS p
            WHERE p.oid = to_regprocedure(
                format('%I.ola_authenticate_api_key(text)', current_schema())
            )
        """), {"worker_role": worker_role}).one_or_none()
        worker_claim_function = conn.execute(text("""
            SELECT p.oid, p.prosecdef, p.proconfig,
                   pg_get_userbyid(p.proowner) AS owner,
                   EXISTS (
                       SELECT 1
                       FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
                       WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                   ) AS public_execute,
                   has_function_privilege(:runtime_role, p.oid, 'EXECUTE') AS runtime_execute,
                   has_function_privilege(:worker_role, p.oid, 'EXECUTE') AS worker_execute,
                   (
                       SELECT array_agg(DISTINCT pg_get_userbyid(acl.grantee))
                       FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
                       WHERE acl.privilege_type = 'EXECUTE'
                         AND acl.grantee <> 0
                         AND acl.grantee <> p.proowner
                         AND pg_get_userbyid(acl.grantee) <> :worker_role
                   ) AS extra_execute_grantees,
                   EXISTS (
                       SELECT 1
                       FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
                       WHERE acl.privilege_type = 'EXECUTE'
                         AND acl.grantee <> p.proowner
                         AND acl.is_grantable
                   ) AS execute_grant_option
            FROM pg_proc AS p
            WHERE p.oid = to_regprocedure(
                format('%I.ola_claim_checkout_jobs(integer,integer)', current_schema())
            )
        """), {"runtime_role": runtime_role, "worker_role": worker_role}).one_or_none()
        role_rows = conn.execute(text("""
            SELECT rolname, rolsuper, rolbypassrls, rolinherit,
                   rolcreatedb, rolcreaterole, rolreplication, rolcanlogin
            FROM pg_roles
            WHERE rolname = ANY(:role_names)
        """), {"role_names": [runtime_role, worker_role]}).all()
        role_memberships = conn.execute(text("""
            SELECT pg_get_userbyid(member) AS member,
                   pg_get_userbyid(roleid) AS granted_role
            FROM pg_auth_members
            WHERE member = ANY(ARRAY[
                pg_catalog.to_regrole(:runtime_role)::oid,
                pg_catalog.to_regrole(:worker_role)::oid
            ])
               OR roleid = ANY(ARRAY[
                pg_catalog.to_regrole(:runtime_role)::oid,
                pg_catalog.to_regrole(:worker_role)::oid
            ])
        """), {
            "runtime_role": runtime_role,
            "worker_role": worker_role,
        }).all()
        worker_table_privileges = conn.execute(text("""
            SELECT
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'SELECT')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'INSERT')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'UPDATE')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'DELETE')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'TRUNCATE')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'REFERENCES')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'TRIGGER')), false),
                COALESCE(bool_or(has_table_privilege(:worker_role,
                    format('%I.%I', current_schema(), scoped.table_name), 'MAINTAIN')), false)
            FROM unnest(CAST(:table_names AS text[])) AS scoped(table_name)
        """), {
            "worker_role": worker_role,
            "table_names": [*rls_tables, "ola_schema_migrations"],
        }).one()
        worker_schema_privileges = conn.execute(text("""
            SELECT has_schema_privilege(:worker_role, current_schema(), 'USAGE'),
                   has_schema_privilege(:worker_role, current_schema(), 'CREATE')
        """), {"worker_role": worker_role}).one()
        runtime_schema_privileges = conn.execute(text("""
            SELECT has_schema_privilege(:runtime_role, current_schema(), 'USAGE'),
                   has_schema_privilege(:runtime_role, current_schema(), 'CREATE')
        """), {"runtime_role": runtime_role}).one()
        schema_acl_privileges = conn.execute(text("""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM pg_namespace AS n
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(n.nspacl, acldefault('n', n.nspowner))
                    ) AS acl
                    WHERE n.nspname = current_schema()
                      AND acl.grantee = 0
                ) AS has_public_acl,
                EXISTS (
                    SELECT 1
                    FROM pg_namespace AS n
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(n.nspacl, acldefault('n', n.nspowner))
                    ) AS acl
                    WHERE n.nspname = current_schema()
                      AND acl.grantee = pg_catalog.to_regrole(:runtime_role)::oid
                      AND acl.is_grantable
                ) AS runtime_has_grant_option,
                EXISTS (
                    SELECT 1
                    FROM pg_namespace AS n
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(n.nspacl, acldefault('n', n.nspowner))
                    ) AS acl
                    WHERE n.nspname = current_schema()
                      AND acl.grantee = pg_catalog.to_regrole(:worker_role)::oid
                      AND acl.is_grantable
                ) AS worker_has_grant_option,
                COALESCE((
                    SELECT array_agg(DISTINCT pg_get_userbyid(acl.grantee)::text)
                    FROM pg_namespace AS n
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(n.nspacl, acldefault('n', n.nspowner))
                    ) AS acl
                    WHERE n.nspname = current_schema()
                      AND acl.grantee <> 0
                      AND acl.grantee <> n.nspowner
                      AND acl.grantee NOT IN (
                          pg_catalog.to_regrole(:runtime_role)::oid,
                          pg_catalog.to_regrole(:worker_role)::oid
                      )
                ), ARRAY[]::text[]) AS extra_schema_grantees
        """), {
            "runtime_role": runtime_role,
            "worker_role": worker_role,
        }).one()
        runtime_table_privileges = conn.execute(text("""
            SELECT scoped.table_name,
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'SELECT'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'INSERT'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'UPDATE'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'DELETE'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'TRUNCATE'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'REFERENCES'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'TRIGGER'),
                   has_table_privilege(:runtime_role, format('%I.%I', current_schema(), scoped.table_name), 'MAINTAIN'),
                   EXISTS (
                       SELECT 1
                       FROM pg_class AS acl_table
                       JOIN pg_namespace AS acl_schema ON acl_schema.oid = acl_table.relnamespace
                       CROSS JOIN LATERAL aclexplode(
                           COALESCE(acl_table.relacl, acldefault('r', acl_table.relowner))
                       ) AS acl
                       WHERE acl_schema.nspname = current_schema()
                         AND acl_table.relname = scoped.table_name
                         AND acl.grantee = 0
                   ) AS has_public_table_acl,
                   EXISTS (
                       SELECT 1
                       FROM pg_class AS acl_table
                       JOIN pg_namespace AS acl_schema ON acl_schema.oid = acl_table.relnamespace
                       CROSS JOIN LATERAL aclexplode(
                           COALESCE(acl_table.relacl, acldefault('r', acl_table.relowner))
                       ) AS acl
                       WHERE acl_schema.nspname = current_schema()
                         AND acl_table.relname = scoped.table_name
                         AND acl.grantee = pg_catalog.to_regrole(:runtime_role)::oid
                         AND acl.is_grantable
                   ) AS runtime_has_grant_option,
                   COALESCE((
                       SELECT array_agg(DISTINCT pg_get_userbyid(acl.grantee)::text)
                       FROM pg_class AS acl_table
                       JOIN pg_namespace AS acl_schema ON acl_schema.oid = acl_table.relnamespace
                       CROSS JOIN LATERAL aclexplode(
                           COALESCE(acl_table.relacl, acldefault('r', acl_table.relowner))
                       ) AS acl
                       WHERE acl_schema.nspname = current_schema()
                         AND acl_table.relname = scoped.table_name
                         AND acl.grantee <> 0
                         AND acl.grantee <> acl_table.relowner
                         AND acl.grantee <> pg_catalog.to_regrole(:runtime_role)::oid
                   ), ARRAY[]::text[]) AS extra_table_grantees
            FROM unnest(CAST(:table_names AS text[])) AS scoped(table_name)
        """), {
            "runtime_role": runtime_role,
            "table_names": [*rls_tables, "ola_schema_migrations"],
        }).all()
        role_state = {
            row[0]: tuple(bool(value) for value in row[1:])
            for row in role_rows
        }
        database_identity = conn.execute(text("""
            SELECT current_user AS current_role, session_user AS session_role
        """)).mappings().one()
        if enforce_runtime_privileges and (
            database_identity["current_role"] != runtime_role
            or database_identity["session_role"] != runtime_role
        ):
            raise RuntimeError(
                "PostgreSQL current_user and session_user must both match the configured runtime role"
            )
        if set(role_state) != {runtime_role, worker_role}:
            raise RuntimeError("PostgreSQL runtime or worker role is missing")
        if role_memberships:
            memberships = ", ".join(f"{row[0]}->{row[1]}" for row in role_memberships)
            raise RuntimeError(
                "PostgreSQL runtime/worker roles must not participate in any role membership: "
                + memberships
            )
        for role_name, flags in role_state.items():
            (
                rolsuper,
                rolbypassrls,
                rolinherit,
                rolcreatedb,
                rolcreaterole,
                rolreplication,
                rolcanlogin,
            ) = flags
            if (
                rolsuper or rolbypassrls or rolinherit or rolcreatedb
                or rolcreaterole or rolreplication or not rolcanlogin
            ):
                raise RuntimeError(
                    f"PostgreSQL role {role_name} must be LOGIN, NOINHERIT, "
                    "NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, and NOREPLICATION"
                )
        role_security = role_state[runtime_role]
        worker_role_security = role_state[worker_role]
    if applied is None:
        raise RuntimeError("PostgreSQL schema migration version is missing")
    if worker_claim_migration is None:
        raise RuntimeError("PostgreSQL worker-claim migration version is missing")
    rls_state = {row[0]: (bool(row[1]), bool(row[2]), row[3]) for row in rls_rows}
    if set(rls_state) != set(rls_tables) or any(not state[0] for state in rls_state.values()):
        raise RuntimeError("PostgreSQL tenant RLS is missing or disabled")
    if enforce_runtime_privileges and any(state[2] == runtime_role for state in rls_state.values()):
        raise RuntimeError("PostgreSQL runtime role must not own tenant-scoped tables")
    if any(state[2] == worker_role for state in rls_state.values()):
        raise RuntimeError("PostgreSQL worker role must not own tenant-scoped tables")
    def normalize_policy_expression(expression):
        # pg_get_expr adds harmless parentheses around identifiers and the
        # complete predicate. Normalize those presentation details while
        # keeping operators, casts, literals and function arguments intact.
        value = re.sub(r"\s+", " ", expression or "").strip()
        value = re.sub(r"\(([A-Za-z_][A-Za-z0-9_$]*)\)(?=::)", r"\1", value)
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            wraps_all = True
            for index, char in enumerate(value):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0 and index != len(value) - 1:
                        wraps_all = False
                        break
            if not wraps_all or depth != 0:
                break
            value = value[1:-1].strip()
        return value

    # Compare actual policy expressions, not just names. A policy can keep its
    # name while being altered to USING (true), which would silently disable isolation.
    policy_state = {
        (row[0], row[1]): {
            "cmd": row[2],
            "permissive": row[3],
            "roles": tuple(row[4] or ()),
            "qual": normalize_policy_expression(row[5]),
            "with_check": normalize_policy_expression(row[6]),
        }
        for row in policy_rows
    }
    expected_policies = {
        "tenants": "id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "api_keys": "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "evidence_records": "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "checkout_orders": "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "checkout_order_controls": "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "checkout_report_reviews": "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "stripe_events": "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)",
        "checkout_execution_jobs": (
            "tenant_id::text = NULLIF(current_setting('ola.tenant_id'::text, true), ''::text)"
        ),
    }
    all_roles = ("public",)
    for table in rls_tables:
        permissive = policy_state.get((table, "ola_tenant_access"))
        restrictive = policy_state.get((table, "ola_tenant_isolation"))
        if not permissive or not restrictive:
            raise RuntimeError("PostgreSQL tenant RLS policies are missing")
        if (
            permissive["cmd"] != "ALL"
            or permissive["permissive"] != "PERMISSIVE"
            or permissive["roles"] != all_roles
            or permissive["qual"] != "true"
            or permissive["with_check"] != "true"
            or restrictive["cmd"] != "ALL"
            or restrictive["permissive"] != "RESTRICTIVE"
            or restrictive["roles"] != all_roles
            or restrictive["qual"] != expected_policies[table]
            or restrictive["with_check"] != expected_policies[table]
        ):
            raise RuntimeError(f"PostgreSQL tenant RLS policy expression is invalid: {table}")
    if auth_function is None:
        raise RuntimeError("PostgreSQL scoped API-key authentication function is missing")
    auth_function_config = auth_function.proconfig or []
    if (
        not auth_function.prosecdef
        or "search_path=pg_catalog" not in auth_function_config
        or auth_function.public_execute
        or not auth_function.runtime_execute
        or auth_function.worker_execute
        or (enforce_runtime_privileges and bool(auth_function.extra_execute_grantees))
        or auth_function.owner == runtime_role
        or auth_function.execute_grant_option
    ):
        raise RuntimeError(
            "PostgreSQL API-key authentication function must be SECURITY DEFINER, "
            "use a fixed search_path, deny PUBLIC execution, grant the current runtime role, "
            "and have no additional non-owner EXECUTE grantees"
        )
    if enforce_runtime_privileges:
        if role_security[0] or role_security[1]:
            raise RuntimeError("PostgreSQL runtime role must not be superuser or BYPASSRLS")
        if not auth_function.runtime_execute or auth_function.public_execute or bool(auth_function.extra_execute_grantees):
            raise RuntimeError("PostgreSQL API-key authentication EXECUTE ACL is not least-privilege")
    if enforce_runtime_privileges and any(evidence_privileges):
        raise RuntimeError("PostgreSQL runtime role must not have UPDATE, DELETE or TRUNCATE on evidence_records")
    if worker_claim_function is None:
        raise RuntimeError("PostgreSQL worker claim function is missing")
    claim_config = worker_claim_function.proconfig or []
    if (
        not worker_claim_function.prosecdef
        or "search_path=pg_catalog" not in claim_config
        or worker_claim_function.public_execute
        or worker_claim_function.runtime_execute
        or not worker_claim_function.worker_execute
        or worker_claim_function.owner in {runtime_role, worker_role}
        or bool(worker_claim_function.extra_execute_grantees)
        or worker_claim_function.execute_grant_option
    ):
        raise RuntimeError(
            "PostgreSQL worker claim function must be SECURITY DEFINER, use fixed search_path, "
            "deny PUBLIC/runtime execution, grant only the worker role, and be owned by a separate migration role"
        )
    if worker_role_security[0] or worker_role_security[1]:
        raise RuntimeError("PostgreSQL worker role must not be superuser or BYPASSRLS")
    expected_runtime_privileges = {
        "tenants": {"SELECT", "INSERT"},
        "api_keys": {"SELECT"},
        "evidence_records": {"SELECT", "INSERT"},
        "stripe_events": {"SELECT", "INSERT", "UPDATE"},
        "checkout_orders": {"SELECT", "INSERT", "UPDATE"},
        "checkout_order_controls": {"SELECT", "INSERT", "UPDATE"},
        "checkout_execution_jobs": {"SELECT", "INSERT", "UPDATE"},
        "checkout_report_reviews": {"SELECT", "INSERT", "UPDATE"},
        "ola_schema_migrations": {"SELECT"},
    }
    privilege_names = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN")
    runtime_privilege_state = {
        row[0]: {name: bool(value) for name, value in zip(privilege_names, row[1:9])}
        for row in runtime_table_privileges
    }
    runtime_table_acl_state = {
        row[0]: {
            "public": bool(row[9]),
            "grant_option": bool(row[10]),
            "extra_grantees": tuple(row[11] or ()),
        }
        for row in runtime_table_privileges
    }
    if set(runtime_privilege_state) != set(expected_runtime_privileges):
        raise RuntimeError("PostgreSQL runtime table privilege inventory is incomplete")
    for table_name, allowed in expected_runtime_privileges.items():
        actual = runtime_privilege_state[table_name]
        if any(actual[name] != (name in allowed) for name in privilege_names):
            raise RuntimeError(
                f"PostgreSQL runtime role table grants are not least-privilege: {table_name}"
            )
        acl_state = runtime_table_acl_state[table_name]
        if acl_state["public"] or acl_state["grant_option"] or acl_state["extra_grantees"]:
            raise RuntimeError(
                f"PostgreSQL runtime table ACL is not least-privilege: {table_name}"
            )
    if not runtime_schema_privileges[0] or runtime_schema_privileges[1]:
        raise RuntimeError("PostgreSQL runtime role must have schema USAGE but must not have schema CREATE")
    if (
        schema_acl_privileges[0]
        or schema_acl_privileges[1]
        or schema_acl_privileges[2]
        or bool(schema_acl_privileges[3])
    ):
        raise RuntimeError("PostgreSQL schema ACL is not least-privilege: PUBLIC, extra roles and grant options are forbidden")
    if any(worker_table_privileges):
        raise RuntimeError("PostgreSQL worker role must not have direct privileges on tenant-owned tables")
    if not worker_schema_privileges[0] or worker_schema_privileges[1]:
        raise RuntimeError("PostgreSQL worker role must have schema USAGE but must not have schema CREATE")
    definitions = {row[0]: (row[1], row[2], row[3]) for row in trigger_rows}
    expected = {"evidence_no_update": "BEFORE UPDATE", "evidence_no_delete": "BEFORE DELETE"}
    for name, action in expected.items():
        trigger_def, function_name, function_def = definitions.get(name, ("", "", ""))
        normalized_trigger = re.sub(r"\s+", " ", trigger_def).upper()
        normalized_function = re.sub(r"\s+", " ", function_def).upper()
        if (
            action not in normalized_trigger
            or function_name != "ola_reject_evidence_mutation"
            or "RAISE EXCEPTION 'EVIDENCE_RECORDS IS APPEND-ONLY'" not in normalized_function
            or "USING ERRCODE = '55000'" not in normalized_function
        ):
            raise RuntimeError("PostgreSQL evidence append-only trigger definition is invalid")


def _migrate_sqlite_private_order_tasks(bind):
    """Move legacy task copies from StripeEvent into the private OLA order row."""
    inspector = inspect(bind)
    order_columns = {column["name"] for column in inspector.get_columns("checkout_orders")}
    api_key_columns = {column["name"] for column in inspector.get_columns("api_keys")}
    with bind.begin() as conn:
        if "task" not in order_columns:
            conn.exec_driver_sql("ALTER TABLE checkout_orders ADD COLUMN task TEXT")
        if "role" not in api_key_columns:
            conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'tenant'")
        conn.exec_driver_sql("""
            UPDATE checkout_orders
            SET task = (
                SELECT stripe_events.task FROM stripe_events
                WHERE stripe_events.event_id = checkout_orders.payment_event_id
                LIMIT 1
            )
            WHERE task IS NULL AND payment_event_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM stripe_events
                          WHERE stripe_events.event_id = checkout_orders.payment_event_id
                            AND stripe_events.task IS NOT NULL)
        """)
        conn.exec_driver_sql("UPDATE stripe_events SET task = NULL WHERE task IS NOT NULL")


def prepare_runtime_schema():
    """Prepare SQLite locally; PostgreSQL is migrated out-of-band and only verified at runtime."""
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
        _migrate_sqlite_private_order_tasks(engine)
        install_append_only_triggers(engine)
        return
    if engine.dialect.name == "postgresql":
        verify_postgres_schema(engine)
        return
    raise RuntimeError(f"unsupported runtime database dialect: {engine.dialect.name}")


def install_postgres_tenant_rls(connection, runtime_role, worker_role):
    """Install tenant RLS plus a role-bound, narrowly scoped worker claim capability."""
    role_pattern = r"[A-Za-z_][A-Za-z0-9_$]{0,62}"
    if not isinstance(runtime_role, str) or re.fullmatch(role_pattern, runtime_role) is None:
        raise ValueError("runtime_role must be a valid unquoted PostgreSQL role name")
    if not isinstance(worker_role, str) or re.fullmatch(role_pattern, worker_role) is None:
        raise ValueError("worker_role must be a valid unquoted PostgreSQL role name")
    if worker_role == runtime_role:
        raise ValueError("worker_role must be distinct from runtime_role")
    schema_name = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    quoted_schema = '"' + schema_name.replace('"', '""') + '"'
    # PUBLIC must not be able to create objects in the application schema.
    connection.exec_driver_sql(
        f"REVOKE CREATE ON SCHEMA {quoted_schema} FROM PUBLIC"
    )

    def revoke_unexpected_function_execute(function_signature: str, allowed_role: str) -> None:
        # Keep only the explicitly allowed runtime identity (or worker identity)
        # in function ACLs. A prior grant to any other role is removed rather
        # than leaving migration and startup verification permanently divergent.
        unexpected_roles = connection.execute(text(f"""
            SELECT DISTINCT pg_get_userbyid(acl.grantee)
            FROM pg_proc AS p
            CROSS JOIN LATERAL aclexplode(
                COALESCE(p.proacl, acldefault('f', p.proowner))
            ) AS acl
            WHERE p.oid = to_regprocedure(
                format('%I.{function_signature}', current_schema())
            )
              AND acl.privilege_type = 'EXECUTE'
              AND acl.grantee <> 0
              AND acl.grantee <> p.proowner
              AND pg_get_userbyid(acl.grantee) <> :allowed_role
        """), {"allowed_role": allowed_role}).all()
        for (role_name,) in unexpected_roles:
            quoted_role = '"' + role_name.replace('"', '""') + '"'
            connection.exec_driver_sql(
                f"REVOKE ALL ON FUNCTION {quoted_schema}.{function_signature} FROM {quoted_role}"
            )

    connection.exec_driver_sql(f"""
    CREATE OR REPLACE FUNCTION {quoted_schema}.ola_authenticate_api_key(p_key_hash text)
    RETURNS TABLE (tenant_id text, api_key_id text, role text)
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $ola$
        SELECT k.tenant_id::text, k.id::text, k.role::text
        FROM {quoted_schema}.api_keys AS k
        WHERE k.key_hash = p_key_hash
        LIMIT 1
    $ola$;
    """)
    existing_roles = {
        row[0] for row in connection.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:role_names)"),
            {"role_names": [runtime_role, worker_role]},
        ).all()
    }
    missing_roles = sorted({runtime_role, worker_role} - existing_roles)
    if missing_roles:
        raise RuntimeError("PostgreSQL required role(s) do not exist: " + ", ".join(missing_roles))

    connection.exec_driver_sql(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.ola_authenticate_api_key(text) FROM PUBLIC"
    )
    revoke_unexpected_function_execute("ola_authenticate_api_key(text)", runtime_role)
    connection.exec_driver_sql(
        f'REVOKE ALL ON FUNCTION {quoted_schema}.ola_authenticate_api_key(text) FROM "{worker_role}"'
    )
    connection.exec_driver_sql(
        f'REVOKE ALL ON FUNCTION {quoted_schema}.ola_authenticate_api_key(text) FROM "{runtime_role}"'
    )
    connection.exec_driver_sql(
        f'GRANT EXECUTE ON FUNCTION {quoted_schema}.ola_authenticate_api_key(text) TO "{runtime_role}"'
    )
    connection.exec_driver_sql(
        f"GRANT USAGE ON SCHEMA {quoted_schema} TO \"{worker_role}\""
    )
    connection.exec_driver_sql(
        f"REVOKE CREATE ON SCHEMA {quoted_schema} FROM \"{worker_role}\""
    )
    connection.exec_driver_sql(
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {quoted_schema} FROM \"{worker_role}\""
    )

    # Worker discovery is a distinct database capability. Its SECURITY DEFINER
    # function returns only opaque job coordinates and a rotating lease token.
    # The worker role receives no direct privilege on any tenant-owned table.
    connection.exec_driver_sql(f"""
    CREATE OR REPLACE FUNCTION {quoted_schema}.ola_claim_checkout_jobs(
        p_limit integer,
        p_stale_after_seconds integer
    )
    RETURNS TABLE (job_id text, tenant_id text, claim_token text)
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = pg_catalog
    AS $ola$
        WITH claim_settings AS (
            SELECT
                FLOOR(EXTRACT(EPOCH FROM pg_catalog.clock_timestamp()))::integer AS now_epoch,
                GREATEST(60, LEAST(COALESCE(p_stale_after_seconds, 900), 86400))::integer AS stale_seconds,
                GREATEST(1, LEAST(COALESCE(p_limit, 20), 100))::integer AS batch_limit
        ),
        candidate_ids AS (
            SELECT jobs.id
            FROM {quoted_schema}.checkout_execution_jobs AS jobs
            CROSS JOIN claim_settings AS settings
            WHERE (
                jobs.status = 'QUEUED'
                AND jobs.attempt_count = 0
                AND (
                    jobs.claim_token IS NULL
                    OR jobs.claimed_at IS NULL
                    OR jobs.claimed_at <= settings.now_epoch - settings.stale_seconds
                )
            ) OR (
                jobs.status = 'RUNNING'
                AND (
                    jobs.started_at IS NULL
                    OR jobs.started_at <= settings.now_epoch - settings.stale_seconds
                )
                AND (
                    jobs.claim_token IS NULL
                    OR jobs.claimed_at IS NULL
                    OR jobs.claimed_at <= settings.now_epoch - settings.stale_seconds
                )
            )
            ORDER BY jobs.created_at ASC, jobs.id ASC
            LIMIT (SELECT batch_limit FROM claim_settings)
            FOR UPDATE OF jobs SKIP LOCKED
        ),
        claimed AS (
            UPDATE {quoted_schema}.checkout_execution_jobs AS jobs
            SET claim_token = pg_catalog.gen_random_uuid()::text,
                claimed_at = (SELECT now_epoch FROM claim_settings)
            FROM candidate_ids
            WHERE jobs.id = candidate_ids.id
            RETURNING jobs.id, jobs.tenant_id, jobs.claim_token
        )
        SELECT claimed.id::text, claimed.tenant_id::text, claimed.claim_token::text
        FROM claimed
    $ola$;
    """)
    connection.exec_driver_sql(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.ola_claim_checkout_jobs(integer, integer) FROM PUBLIC"
    )
    connection.exec_driver_sql(
        f'REVOKE ALL ON FUNCTION {quoted_schema}.ola_claim_checkout_jobs(integer, integer) FROM "{runtime_role}"'
    )
    revoke_unexpected_function_execute("ola_claim_checkout_jobs(integer, integer)", worker_role)
    connection.exec_driver_sql(
        f'REVOKE ALL ON FUNCTION {quoted_schema}.ola_claim_checkout_jobs(integer, integer) FROM "{worker_role}"'
    )
    connection.exec_driver_sql(
        f'GRANT EXECUTE ON FUNCTION {quoted_schema}.ola_claim_checkout_jobs(integer, integer) TO "{worker_role}"'
    )

    # Schema ACL is private to the migration owner and two application roles.
    # Remove PUBLIC and any stale direct grantees before granting USAGE only.
    connection.exec_driver_sql(
        f"REVOKE ALL ON SCHEMA {quoted_schema} FROM PUBLIC"
    )
    unexpected_schema_grantees = connection.execute(text("""
        SELECT DISTINCT pg_get_userbyid(acl.grantee)::text
        FROM pg_namespace AS n
        CROSS JOIN LATERAL aclexplode(
            COALESCE(n.nspacl, acldefault('n', n.nspowner))
        ) AS acl
        WHERE n.nspname = :schema_name
          AND acl.grantee <> 0
          AND acl.grantee <> n.nspowner
          AND acl.grantee NOT IN (
              pg_catalog.to_regrole(:runtime_role)::oid,
              pg_catalog.to_regrole(:worker_role)::oid
          )
    """), {
        "schema_name": schema_name,
        "runtime_role": runtime_role,
        "worker_role": worker_role,
    }).all()
    for (grantee,) in unexpected_schema_grantees:
        quoted_grantee = '"' + grantee.replace('"', '""') + '"'
        connection.exec_driver_sql(
            f"REVOKE ALL ON SCHEMA {quoted_schema} FROM {quoted_grantee}"
        )
    connection.exec_driver_sql(
        f'REVOKE ALL ON SCHEMA {quoted_schema} FROM "{runtime_role}"'
    )
    connection.exec_driver_sql(
        f'REVOKE ALL ON SCHEMA {quoted_schema} FROM "{worker_role}"'
    )
    connection.exec_driver_sql(
        f'GRANT USAGE ON SCHEMA {quoted_schema} TO "{runtime_role}"'
    )
    connection.exec_driver_sql(
        f'GRANT USAGE ON SCHEMA {quoted_schema} TO "{worker_role}"'
    )
    runtime_table_grants = {
        "tenants": "SELECT, INSERT",
        "api_keys": "SELECT",
        "evidence_records": "SELECT, INSERT",
        "stripe_events": "SELECT, INSERT, UPDATE",
        "checkout_orders": "SELECT, INSERT, UPDATE",
        "checkout_order_controls": "SELECT, INSERT, UPDATE",
        "checkout_execution_jobs": "SELECT, INSERT, UPDATE",
        "checkout_report_reviews": "SELECT, INSERT, UPDATE",
        "ola_schema_migrations": "SELECT",
    }
    for table_name, privileges in runtime_table_grants.items():
        qualified_table = f'{quoted_schema}."{table_name}"'
        connection.exec_driver_sql(
            f'REVOKE ALL PRIVILEGES ON TABLE {qualified_table} FROM PUBLIC'
        )
        unexpected_table_grantees = connection.execute(text("""
            SELECT DISTINCT pg_get_userbyid(acl.grantee)
            FROM pg_class AS table_acl
            JOIN pg_namespace AS table_schema ON table_schema.oid = table_acl.relnamespace
            CROSS JOIN LATERAL aclexplode(
                COALESCE(table_acl.relacl, acldefault('r', table_acl.relowner))
            ) AS acl
            WHERE table_schema.nspname = :schema_name
              AND table_acl.relname = :table_name
              AND acl.grantee <> 0
              AND acl.grantee <> table_acl.relowner
              AND pg_get_userbyid(acl.grantee) <> :runtime_role
        """), {
            "schema_name": schema_name,
            "table_name": table_name,
            "runtime_role": runtime_role,
        }).all()
        for (grantee,) in unexpected_table_grantees:
            quoted_grantee = '"' + grantee.replace('"', '""') + '"'
            connection.exec_driver_sql(
                f"REVOKE ALL PRIVILEGES ON TABLE {qualified_table} FROM {quoted_grantee}"
            )
        connection.exec_driver_sql(
            f'REVOKE ALL PRIVILEGES ON TABLE {qualified_table} FROM "{runtime_role}"'
        )
        connection.exec_driver_sql(
            f'GRANT {privileges} ON TABLE {qualified_table} TO "{runtime_role}"'
        )

    tenant_policies = {
        "tenants": "id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "api_keys": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "evidence_records": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_orders": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_order_controls": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_report_reviews": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "stripe_events": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        # No worker-wide escape hatch: the API runtime role remains tenant-scoped.
        "checkout_execution_jobs": (
            "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')"
        ),
    }
    for table_name, predicate in tenant_policies.items():
        connection.exec_driver_sql(
            f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'
        )
        connection.exec_driver_sql(
            f'DROP POLICY IF EXISTS ola_tenant_access ON "{table_name}"'
        )
        connection.exec_driver_sql(
            f'DROP POLICY IF EXISTS ola_tenant_isolation ON "{table_name}"'
        )
        connection.exec_driver_sql(
            f'CREATE POLICY ola_tenant_access ON "{table_name}" '
            f'AS PERMISSIVE FOR ALL USING (true) WITH CHECK (true)'
        )
        connection.exec_driver_sql(
            f'CREATE POLICY ola_tenant_isolation ON "{table_name}" '
            f'AS RESTRICTIVE FOR ALL USING ({predicate}) WITH CHECK ({predicate})'
        )


def migrate_postgres_schema(target_engine, *, runtime_role, worker_role=None):
    """Apply the additive ORM baseline, RLS, and isolated worker claim capability."""
    if target_engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL migration URL is required")
    worker_role = worker_role or os.getenv("OLA_DATABASE_WORKER_ROLE", "ola_worker").strip()
    role_pattern = r"[A-Za-z_][A-Za-z0-9_$]{0,62}"
    if not isinstance(runtime_role, str) or re.fullmatch(role_pattern, runtime_role) is None:
        raise ValueError("runtime_role must be a valid unquoted PostgreSQL role name")
    if not isinstance(worker_role, str) or re.fullmatch(role_pattern, worker_role) is None:
        raise ValueError("worker_role must be a valid unquoted PostgreSQL role name")
    if worker_role == runtime_role:
        raise ValueError("worker_role must be distinct from runtime_role")
    # Register all ORM tables before create_all.
    from . import models  # noqa: F401

    with target_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ola_schema_migrations (
                version VARCHAR(100) PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        Base.metadata.create_all(bind=conn)
        conn.execute(text("ALTER TABLE checkout_orders ADD COLUMN IF NOT EXISTS task TEXT"))
        conn.execute(text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'tenant'"))
        conn.execute(text("ALTER TABLE stripe_events ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)"))
        conn.execute(text("ALTER TABLE checkout_execution_jobs ADD COLUMN IF NOT EXISTS claimed_at INTEGER"))
        conn.execute(text("""
            UPDATE checkout_orders AS orders
            SET task = events.task
            FROM stripe_events AS events
            WHERE orders.payment_event_id = events.event_id
              AND orders.task IS NULL AND events.task IS NOT NULL
        """))
        conn.execute(text("UPDATE stripe_events SET task = NULL WHERE task IS NOT NULL"))
        create_postgres_append_only_triggers(conn)
        install_postgres_tenant_rls(conn, runtime_role, worker_role)
        conn.execute(text("""
            INSERT INTO ola_schema_migrations(version, description)
            VALUES (:version, :description)
            ON CONFLICT (version) DO NOTHING
        """), {
            "version": "ola_paid_order_outbox_v1",
            "description": "Additive ORM baseline plus evidence append-only triggers",
        })
        conn.execute(text("""
            INSERT INTO ola_schema_migrations(version, description)
            VALUES (:version, :description)
            ON CONFLICT (version) DO NOTHING
        """), {
            "version": "ola_paid_order_privacy_v2",
            "description": "Store paid order request task only in OLA; clear task text from Stripe event mirror",
        })
        conn.execute(text("""
            INSERT INTO ola_schema_migrations(version, description)
            VALUES (:version, :description)
            ON CONFLICT (version) DO NOTHING
        """), {
            "version": "ola_paid_order_report_review_v3",
            "description": "Add order-bound independent report review and authenticated customer delivery records",
        })
        conn.execute(text("""
            INSERT INTO ola_schema_migrations(version, description)
            VALUES (:version, :description)
            ON CONFLICT (version) DO NOTHING
        """), {
            "version": "ola_tenant_rls_v4",
            "description": "Enable transaction-local tenant RLS and scoped API-key authentication",
        })
        conn.execute(text("""
            INSERT INTO ola_schema_migrations(version, description)
            VALUES (:version, :description)
            ON CONFLICT (version) DO NOTHING
        """), {
            "version": "ola_tenant_worker_claim_v5",
            "description": "Add role-bound SECURITY DEFINER outbox claim function with expiring leases",
        })
    verify_postgres_schema(
        target_engine, enforce_runtime_privileges=False,
        runtime_role=runtime_role, worker_role=worker_role,
    )


def append_evidence_atomic(tenant_id, record_type, payload, *, producer_id="ola_runtime", deduplicate=False):
    """Serialize all evidence writers before reading a tenant tip.

    SQLite uses BEGIN IMMEDIATE; PostgreSQL uses a transaction-scoped
    advisory lock keyed by tenant. Both serialize sequence allocation before
    reading seq/prev_hash. Unique(tenant_id, seq) remains a final guard.
    """
    from .hashchain import GENESIS_HASH, sealed_payload_json, compute_record_hash_v2
    from .models import EvidenceRecord

    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant_id required for evidence append")
    if not isinstance(record_type, str) or not record_type:
        raise ValueError("record_type required for evidence append")
    payload_json = sealed_payload_json(record_type, payload, producer=producer_id)
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        if deduplicate:
            existing = db.scalar(select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.record_type == record_type,
                EvidenceRecord.payload_json == payload_json,
            ))
            if existing is not None:
                existing_result = {
                    "id": existing.id,
                    "tenant_id": tenant_id,
                    "seq": existing.seq,
                    "record_hash": existing.record_hash,
                }
                db.rollback()
                return existing_result
        last = db.scalar(select(EvidenceRecord)
                         .where(EvidenceRecord.tenant_id == tenant_id)
                         .order_by(EvidenceRecord.seq.desc()))
        seq = last.seq + 1 if last is not None else 0
        previous = last.record_hash if last is not None else GENESIS_HASH
        record_id = str(uuid.uuid4())
        digest = compute_record_hash_v2(tenant_id, seq, previous, record_type,
                                        producer_id, payload_json)
        db.add(EvidenceRecord(
            id=record_id, tenant_id=tenant_id, seq=seq, record_type=record_type,
            payload_json=payload_json, prev_hash=previous, record_hash=digest,
        ))
        db.commit()
        return {"id": record_id, "tenant_id": tenant_id, "seq": seq,
                "record_hash": digest}
