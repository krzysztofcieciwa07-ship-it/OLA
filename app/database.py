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
    """Set transaction-local RLS context on every PostgreSQL ORM transaction."""
    if connection.dialect.name != "postgresql":
        return
    tenant_id = current_tenant_id()
    if tenant_id:
        connection.execute(
            text("SELECT set_config('ola.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
    if worker_mode_enabled():
        connection.execute(text("SELECT set_config('ola.worker_mode', 'on', true)"))


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


def verify_postgres_schema(bind, *, enforce_runtime_privileges=True):
    """Fail closed unless the migrated schema and immutable evidence controls are present."""
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
            "attempt_count", "claim_token", "started_at", "finished_at", "run_id",
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
            SELECT c.relname, c.relrowsecurity, pg_get_userbyid(c.relowner)
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = ANY(:table_names)
        """), {"table_names": list(rls_tables)}).all()
        policy_rows = conn.execute(text("""
            SELECT tablename, policyname, cmd
            FROM pg_policies
            WHERE schemaname = current_schema()
              AND tablename = ANY(:table_names)
        """), {"table_names": list(rls_tables)}).all()
        auth_function = conn.execute(text(
            "SELECT to_regprocedure('ola_authenticate_api_key(text)')"
        )).scalar_one()
        if enforce_runtime_privileges:
            role_security = conn.execute(text("""
                SELECT rolsuper, rolbypassrls
                FROM pg_roles WHERE rolname = current_user
            """)).one()
        else:
            role_security = (False, False)
    if applied is None:
        raise RuntimeError("PostgreSQL schema migration version is missing")
    rls_state = {row[0]: (bool(row[1]), row[2]) for row in rls_rows}
    if set(rls_state) != set(rls_tables) or any(not state[0] for state in rls_state.values()):
        raise RuntimeError("PostgreSQL tenant RLS is missing or disabled")
    policy_state = {(row[0], row[1], row[2]) for row in policy_rows}
    if any((table, "ola_tenant_isolation", "ALL") not in policy_state for table in rls_tables):
        raise RuntimeError("PostgreSQL tenant RLS policy is missing")
    if auth_function is None:
        raise RuntimeError("PostgreSQL scoped API-key authentication function is missing")
    if enforce_runtime_privileges:
        if role_security[0] or role_security[1]:
            raise RuntimeError("PostgreSQL runtime role must not be superuser or BYPASSRLS")
        if any(owner == "current_user" for _enabled, owner in rls_state.values()):
            raise RuntimeError("PostgreSQL runtime role must not own tenant-scoped tables")
    if enforce_runtime_privileges and any(evidence_privileges):
        raise RuntimeError("PostgreSQL runtime role must not have UPDATE, DELETE or TRUNCATE on evidence_records")
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


def install_postgres_tenant_rls(connection):
    """Install fail-closed RLS policies for every tenant-owned PostgreSQL table."""
    connection.exec_driver_sql("""
    CREATE OR REPLACE FUNCTION ola_authenticate_api_key(p_key_hash text)
    RETURNS TABLE (tenant_id text, api_key_id text, role text)
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $ola$
        SELECT k.tenant_id::text, k.id::text, k.role::text
        FROM public.api_keys AS k
        WHERE k.key_hash = p_key_hash
        LIMIT 1
    $ola$;
    """)
    connection.exec_driver_sql(
        "GRANT EXECUTE ON FUNCTION ola_authenticate_api_key(text) TO PUBLIC"
    )

    tenant_policies = {
        "tenants": "id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "api_keys": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "evidence_records": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_orders": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_order_controls": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_report_reviews": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "stripe_events": "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')",
        "checkout_execution_jobs": (
            "tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '') "
            "OR current_setting('ola.worker_mode', true) = 'on'"
        ),
    }
    for table_name, predicate in tenant_policies.items():
        connection.exec_driver_sql(
            f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'
        )
        connection.exec_driver_sql(
            f'DROP POLICY IF EXISTS ola_tenant_isolation ON "{table_name}"'
        )
        connection.exec_driver_sql(
            f'CREATE POLICY ola_tenant_isolation ON "{table_name}" '
            f'FOR ALL USING ({predicate}) WITH CHECK ({predicate})'
        )


def migrate_postgres_schema(target_engine):
    """Apply the additive ORM baseline and append-only triggers with a migration role."""
    if target_engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL migration URL is required")
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
        conn.execute(text("""
            UPDATE checkout_orders AS orders
            SET task = events.task
            FROM stripe_events AS events
            WHERE orders.payment_event_id = events.event_id
              AND orders.task IS NULL AND events.task IS NOT NULL
        """))
        conn.execute(text("UPDATE stripe_events SET task = NULL WHERE task IS NOT NULL"))
        create_postgres_append_only_triggers(conn)
        install_postgres_tenant_rls(conn)
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
    verify_postgres_schema(target_engine, enforce_runtime_privileges=False)


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
