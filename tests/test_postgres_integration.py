"""Real PostgreSQL tests. Set OLA_TEST_POSTGRES_URL to enable them."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.tenant_context import tenant_scope

POSTGRES_URL = os.getenv("OLA_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="OLA_TEST_POSTGRES_URL is not configured")


@pytest.fixture
def postgres_db(monkeypatch):
    from app import database
    from app.models import Tenant

    admin_engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    schema = "ola_test_" + uuid.uuid4().hex
    runtime_role = "ola_rt_" + uuid.uuid4().hex[:12]
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'CREATE ROLE "{runtime_role}" NOLOGIN')

    search_path = f"-csearch_path={schema}"
    migration_engine = create_engine(
        POSTGRES_URL,
        pool_pre_ping=True,
        connect_args={"options": search_path},
    )
    runtime_engine = None
    try:
        database.migrate_postgres_schema(migration_engine, runtime_role=runtime_role)
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{runtime_role}"')
            grants = {
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
            for table_name, privileges in grants.items():
                conn.exec_driver_sql(
                    f'GRANT {privileges} ON TABLE "{schema}"."{table_name}" TO "{runtime_role}"'
                )

        runtime_engine = create_engine(
            POSTGRES_URL,
            pool_pre_ping=True,
            connect_args={"options": search_path},
        )

        @event.listens_for(runtime_engine, "connect")
        def assume_runtime_role(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET ROLE "{runtime_role}"')
            cursor.close()
            # SET ROLE is transactional: persist the session role before the
            # SQLAlchemy pool can roll back a check-in transaction.
            dbapi_connection.commit()

        monkeypatch.setattr(database, "SessionLocal", sessionmaker(
            bind=runtime_engine, autocommit=False, autoflush=False,
        ))
        database.verify_postgres_schema(runtime_engine)
        yield database, runtime_engine, migration_engine, admin_engine, runtime_role, schema
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        migration_engine.dispose()
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'DROP OWNED BY "{runtime_role}"')
            conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{runtime_role}"')
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()


def test_postgres_concurrent_evidence_appends_are_serialized_and_immutable(postgres_db):
    database, runtime_engine, migration_engine, _admin_engine, runtime_role, _schema = postgres_db
    from app.hashchain import verify_chain
    from app.models import EvidenceRecord, Tenant

    # The restricted runtime role has only SELECT/INSERT on evidence_records.
    database.verify_postgres_schema(runtime_engine)
    tenant_id = str(uuid.uuid4())
    with tenant_scope(tenant_id):
        with database.SessionLocal() as db:
            db.add(Tenant(id=tenant_id, name="PostgreSQL integration tenant"))
            db.commit()

    def append_event(index):
        with tenant_scope(tenant_id):
            return database.append_evidence_atomic(
                tenant_id, "integration.append", {"index": index},
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(append_event, range(32)))

    assert len({item["id"] for item in results}) == 32
    with tenant_scope(tenant_id):
        with database.SessionLocal() as db:
            rows = db.scalars(
                select(EvidenceRecord)
                .where(EvidenceRecord.tenant_id == tenant_id)
                .order_by(EvidenceRecord.seq.asc())
            ).all()
    assert [row.seq for row in rows] == list(range(32))
    records = [{
        "id": row.id, "tenant_id": row.tenant_id, "seq": row.seq,
        "prev_hash": row.prev_hash, "record_hash": row.record_hash,
        "record_type": row.record_type, "payload_json": row.payload_json,
    } for row in rows]
    assert verify_chain(records)[0] is True

    # The DB-level triggers still protect against privileged accidental writes.
    with migration_engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.exec_driver_sql(
                "UPDATE evidence_records SET payload_json = '{}' WHERE id = %s",
                (rows[0].id,),
            )
    with migration_engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.exec_driver_sql(
                "DELETE FROM evidence_records WHERE id = %s",
                (rows[0].id,),
            )

    # The runtime startup check must reject an accidentally over-privileged role.
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT UPDATE, TRUNCATE ON TABLE "{_schema}".evidence_records TO "{runtime_role}"'
        )
    with pytest.raises(RuntimeError, match="must not have UPDATE, DELETE or TRUNCATE"):
        database.verify_postgres_schema(runtime_engine)
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE UPDATE, TRUNCATE ON TABLE "{_schema}".evidence_records FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(runtime_engine)

    # Startup must fail closed if a policy keeps its name but loses isolation.
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'ALTER POLICY ola_tenant_isolation ON "{_schema}".evidence_records USING (true) WITH CHECK (true)'
        )
    with pytest.raises(RuntimeError, match="policy expression is invalid: evidence_records"):
        database.verify_postgres_schema(runtime_engine)
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f"ALTER POLICY ola_tenant_isolation ON \"{_schema}\".evidence_records "
            "USING (tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')) "
            "WITH CHECK (tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), ''))"
        )
    database.verify_postgres_schema(runtime_engine)

    # Startup must fail closed if a tenant table loses RLS.
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE "{_schema}".evidence_records DISABLE ROW LEVEL SECURITY')
    with pytest.raises(RuntimeError, match="tenant RLS is missing or disabled"):
        database.verify_postgres_schema(runtime_engine)
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE "{_schema}".evidence_records ENABLE ROW LEVEL SECURITY')
    database.verify_postgres_schema(runtime_engine)


def test_postgres_rls_isolates_tenant_rows_and_preserves_secure_api_key_lookup(postgres_db):
    database, runtime_engine, migration_engine, _admin_engine, _runtime_role, _schema = postgres_db

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    key_a = "a" * 64
    key_b = "b" * 64
    key_a_id = str(uuid.uuid4())
    key_b_id = str(uuid.uuid4())
    order_ids = [str(uuid.uuid4()) for _ in range(6)]
    with migration_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
            [{"id": tenant_a, "name": "tenant-a"}, {"id": tenant_b, "name": "tenant-b"}],
        )
        conn.execute(
            text("INSERT INTO api_keys (id, tenant_id, key_hash, role) VALUES (:id, :tenant_id, :key_hash, 'tenant')"),
            [
                {"id": key_a_id, "tenant_id": tenant_a, "key_hash": key_a},
                {"id": key_b_id, "tenant_id": tenant_b, "key_hash": key_b},
            ],
        )
        # Seed real tenant-B rows so SELECT isolation assertions are meaningful.
        conn.execute(
            text("""
                INSERT INTO checkout_orders
                    (id, tenant_id, idempotency_key_hash, request_hash, status, created_at)
                VALUES
                    (:id0, :tenant_b, :idem0, :request_hash, 'CHECKOUT_CREATED', 0),
                    (:id1, :tenant_b, :idem1, :request_hash, 'CHECKOUT_CREATED', 0),
                    (:id2, :tenant_b, :idem2, :request_hash, 'CHECKOUT_CREATED', 0),
                    (:id3, :tenant_b, :idem3, :request_hash, 'CHECKOUT_CREATED', 0),
                    (:id4, :tenant_b, :idem4, :request_hash, 'CHECKOUT_CREATED', 0),
                    (:id5, :tenant_b, :idem5, :request_hash, 'CHECKOUT_CREATED', 0)
            """),
            {
                "tenant_b": tenant_b, "request_hash": "a" * 64,
                **{f"id{i}": order_ids[i] for i in range(6)},
                **{f"idem{i}": uuid.uuid4().hex for i in range(6)},
            },
        )
        conn.execute(
            text("""
                INSERT INTO evidence_records
                    (id, tenant_id, seq, record_type, payload_json, prev_hash, record_hash)
                VALUES (:id, :tenant_b, 0, 'seed', '{}', :genesis, :digest)
            """),
            {"id": str(uuid.uuid4()), "tenant_b": tenant_b, "genesis": "0" * 64, "digest": "1" * 64},
        )
        conn.execute(
            text("""
                INSERT INTO stripe_events (id, tenant_id, event_id, status)
                VALUES (:id, :tenant_b, :event_id, 'PROCESSING')
            """),
            {"id": str(uuid.uuid4()), "tenant_b": tenant_b, "event_id": "evt_rls_seed_" + uuid.uuid4().hex},
        )
        conn.execute(
            text("""
                INSERT INTO checkout_order_controls (id, order_id, tenant_id, requester_id, status)
                VALUES (:id, :order_id, :tenant_b, :requester_id, 'PENDING')
            """),
            {"id": str(uuid.uuid4()), "order_id": order_ids[0], "tenant_b": tenant_b, "requester_id": key_b_id},
        )
        conn.execute(
            text("""
                INSERT INTO checkout_execution_jobs
                    (id, tenant_id, order_id, approval_record_hash, task, status, attempt_count, created_at)
                VALUES (:id, :tenant_b, :order_id, :approval_hash, 'seed task', 'QUEUED', 0, 0)
            """),
            {"id": str(uuid.uuid4()), "tenant_b": tenant_b, "order_id": order_ids[1], "approval_hash": "b" * 64},
        )
        conn.execute(
            text("""
                INSERT INTO checkout_report_reviews
                    (id, order_id, tenant_id, reviewer_id, status, report_sha256,
                     reviewed_tip_hash, reason, reviewed_at)
                VALUES (:id, :order_id, :tenant_b, :reviewer_id, 'PENDING',
                        :report_hash, :tip_hash, 'seed review', 0)
            """),
            {
                "id": str(uuid.uuid4()), "order_id": order_ids[2], "tenant_b": tenant_b,
                "reviewer_id": key_b_id, "report_hash": "c" * 64, "tip_hash": "0" * 64,
            },
        )

    # No tenant context is fail-closed: tenant-scoped tables expose no rows.
    with database.SessionLocal() as db:
        assert db.execute(text("SELECT id FROM tenants")).all() == []
        assert db.execute(text("SELECT id FROM api_keys")).all() == []

    # A transaction-local tenant context exposes only that tenant's rows.
    with tenant_scope(tenant_a):
        with database.SessionLocal() as db:
            assert db.execute(text("SELECT id FROM tenants")).scalars().all() == [tenant_a]
            assert db.execute(text("SELECT tenant_id FROM api_keys")).scalars().all() == [tenant_a]
            # Every tenant-owned table must hide tenant B in tenant A's context.
            tenant_tables = {
                "evidence_records": ("id", "tenant_id"),
                "stripe_events": ("id", "tenant_id"),
                "checkout_orders": ("id", "tenant_id"),
                "checkout_order_controls": ("id", "tenant_id"),
                "checkout_execution_jobs": ("id", "tenant_id"),
                "checkout_report_reviews": ("id", "tenant_id"),
            }
            for table_name, (row_id_column, tenant_column) in tenant_tables.items():
                visible = db.execute(
                    text(f"SELECT {row_id_column} FROM {table_name} WHERE {tenant_column} = :tenant_b"),
                    {"tenant_b": tenant_b},
                ).scalars().all()
                assert visible == [], (table_name, visible)
                # Prove WITH CHECK also rejects cross-tenant inserts, not just reads.
                insert_columns = {
                    "evidence_records": "(id, tenant_id, seq, record_type, payload_json, prev_hash, record_hash)",
                    "stripe_events": "(id, tenant_id, event_id, status)",
                    "checkout_orders": "(id, tenant_id, idempotency_key_hash, request_hash, status, created_at)",
                    "checkout_order_controls": "(id, order_id, tenant_id, requester_id, status)",
                    "checkout_execution_jobs": "(id, tenant_id, order_id, approval_record_hash, task, status, attempt_count, created_at)",
                    "checkout_report_reviews": "(id, order_id, tenant_id, reviewer_id, status, report_sha256, reviewed_tip_hash, reason, reviewed_at)",
                }
                values = {
                    "evidence_records": "(:id, :tenant_b, 1, 'probe', '{}', :genesis, :digest)",
                    "stripe_events": "(:id, :tenant_b, :event_id, 'PROCESSING')",
                    "checkout_orders": "(:id, :tenant_b, :idem, :request_hash, 'CHECKOUT_CREATED', 0)",
                    "checkout_order_controls": "(:id, :order_id_control, :tenant_b, :requester_id, 'PENDING')",
                    "checkout_execution_jobs": "(:id, :tenant_b, :order_id_job, :approval_hash, 'probe', 'QUEUED', 0, 0)",
                    "checkout_report_reviews": "(:id, :order_id_review, :tenant_b, :reviewer_id, 'PENDING', :report_hash, :tip_hash, 'probe', 0)",
                }
                params = {
                    "id": str(uuid.uuid4()), "tenant_b": tenant_b,
                    "event_id": "evt_rls_probe_" + uuid.uuid4().hex,
                    "idem": uuid.uuid4().hex, "request_hash": "a" * 64,
                    "order_id_control": order_ids[3], "order_id_job": order_ids[4],
                    "order_id_review": order_ids[5], "requester_id": key_b_id,
                    "approval_hash": "b" * 64, "genesis": "0" * 64, "digest": "2" * 64,
                    "reviewer_id": key_b_id, "report_hash": "c" * 64,
                    "tip_hash": "0" * 64,
                }
                with pytest.raises(DBAPIError):
                    db.execute(
                        text(f"INSERT INTO {table_name} {insert_columns[table_name]} VALUES {values[table_name]}"),
                        params,
                    )
                    db.rollback()

    # Setting the legacy worker GUC must not grant cross-tenant visibility.
    with database.SessionLocal() as db:
        db.execute(text("SELECT set_config('ola.worker_mode', 'on', true)"))
        visible = db.execute(
            text("SELECT DISTINCT tenant_id FROM checkout_execution_jobs")
        ).scalars().all()
        assert visible == [], visible

    # Authentication is the only pre-tenant lookup and is mediated by a
    # narrowly scoped SECURITY DEFINER function, not direct table access.
    with database.SessionLocal() as db:
        assert db.execute(text("""
            SELECT has_function_privilege(
                current_user,
                to_regprocedure('ola_authenticate_api_key(text)'),
                'EXECUTE'
            )
        """)).scalar_one() is True
        assert db.execute(text("""
            SELECT NOT EXISTS (
                SELECT 1
                FROM pg_proc AS p
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(p.proacl, acldefault('f', p.proowner))
                ) AS acl
                WHERE p.oid = to_regprocedure('ola_authenticate_api_key(text)')
                  AND acl.grantee = 0
                  AND acl.privilege_type = 'EXECUTE'
            )
        """)).scalar_one() is True

    # Startup must reject a function that has been re-exposed to PUBLIC.
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "GRANT EXECUTE ON FUNCTION ola_authenticate_api_key(text) TO PUBLIC"
        )
    with pytest.raises(RuntimeError, match="deny PUBLIC execution"):
        database.verify_postgres_schema(runtime_engine)
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "REVOKE EXECUTE ON FUNCTION ola_authenticate_api_key(text) FROM PUBLIC"
        )
    database.verify_postgres_schema(runtime_engine)

    with database.SessionLocal() as db:
        authenticated = db.execute(
            text("SELECT tenant_id, api_key_id, role FROM ola_authenticate_api_key(:key_hash)"),
            {"key_hash": key_b},
        ).one()
    assert authenticated.tenant_id == tenant_b
    assert authenticated.role == "tenant"
