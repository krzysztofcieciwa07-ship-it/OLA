"""Real PostgreSQL tests. Set OLA_TEST_POSTGRES_URL to enable them."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
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
    worker_role = "ola_wr_" + uuid.uuid4().hex[:12]
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(
            f'CREATE ROLE "{runtime_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD 'ola_runtime_test_only'"
        )
        conn.exec_driver_sql(
            f'CREATE ROLE "{worker_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD 'ola_worker_test_only'"
        )

    search_path = f"-csearch_path={schema}"
    migration_engine = create_engine(
        POSTGRES_URL,
        pool_pre_ping=True,
        connect_args={"options": search_path},
    )
    runtime_engine = None
    try:
        monkeypatch.setenv("OLA_DATABASE_WORKER_ROLE", worker_role)
        database.migrate_postgres_schema(
            migration_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
        runtime_url = make_url(POSTGRES_URL).set(
            username=runtime_role,
            password="ola_runtime_test_only",
        )
        runtime_engine = create_engine(
            runtime_url,
            pool_pre_ping=True,
            connect_args={"options": search_path},
        )

        monkeypatch.setattr(database, "SessionLocal", sessionmaker(
            bind=runtime_engine, autocommit=False, autoflush=False,
        ))
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
        yield database, runtime_engine, migration_engine, admin_engine, runtime_role, schema, worker_role
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        migration_engine.dispose()
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'DROP OWNED BY "{worker_role}"')
            conn.exec_driver_sql(f'DROP OWNED BY "{runtime_role}"')
            conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{worker_role}"')
            conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{runtime_role}"')
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()


def test_postgres_concurrent_evidence_appends_are_serialized_and_immutable(postgres_db):
    database, runtime_engine, migration_engine, _admin_engine, runtime_role, _schema, worker_role = postgres_db
    from app.hashchain import verify_chain
    from app.models import EvidenceRecord, Tenant

    # The restricted runtime role has only SELECT/INSERT on evidence_records.
    database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)
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
        database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE UPDATE, TRUNCATE ON TABLE "{_schema}".evidence_records FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)

    # Startup must fail closed if a policy keeps its name but loses isolation.
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'ALTER POLICY ola_tenant_isolation ON "{_schema}".evidence_records USING (true) WITH CHECK (true)'
        )
    with pytest.raises(RuntimeError, match="policy expression is invalid: evidence_records"):
        database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f"ALTER POLICY ola_tenant_isolation ON \"{_schema}\".evidence_records "
            "USING (tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), '')) "
            "WITH CHECK (tenant_id::text = NULLIF(current_setting('ola.tenant_id', true), ''))"
        )
    database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)

    # Startup must fail closed if a tenant table loses RLS.
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE "{_schema}".evidence_records DISABLE ROW LEVEL SECURITY')
    with pytest.raises(RuntimeError, match="tenant RLS is missing or disabled"):
        database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)
    with _admin_engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE "{_schema}".evidence_records ENABLE ROW LEVEL SECURITY')
    database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)


def test_postgres_worker_claim_is_role_bound_and_uses_expiring_leases(postgres_db):
    database, runtime_engine, migration_engine, admin_engine, runtime_role, schema, worker_role = postgres_db

    # A worker login must claim through a narrow function; it must not gain
    # SELECT/UPDATE access to tenant-owned job rows or reuse the API role.
    with migration_engine.begin() as conn:
        columns = {item["name"] for item in database.inspect(migration_engine).get_columns("checkout_execution_jobs")}
        assert "claimed_at" in columns, "worker claim lease timestamp is missing"
        claim_oid = conn.execute(text("""
            SELECT to_regprocedure(
                format('%I.ola_claim_checkout_jobs(integer,integer)', current_schema())
            )::oid
        """)).scalar_one()
        assert claim_oid is not None, "role-bound PostgreSQL claim function is missing"
        acl = conn.execute(text("""
            SELECT p.prosecdef,
                   p.proconfig,
                   EXISTS (
                       SELECT 1 FROM aclexplode(
                           COALESCE(p.proacl, acldefault('f', p.proowner))
                       ) AS acl
                       WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                   ) AS public_execute,
                   has_function_privilege(:worker_role, p.oid, 'EXECUTE') AS worker_execute,
                   has_function_privilege(:runtime_role, p.oid, 'EXECUTE') AS runtime_execute
            FROM pg_proc AS p
            WHERE p.oid = :claim_oid
        """), {
            "worker_role": worker_role, "runtime_role": runtime_role, "claim_oid": claim_oid,
        }).one()
        assert acl.prosecdef is True
        assert "search_path=pg_catalog" in (acl.proconfig or [])
        assert acl.public_execute is False
        assert acl.worker_execute is True
        assert acl.runtime_execute is False
        worker_table_privileges = conn.execute(text("""
            SELECT has_table_privilege(:worker_role, 'checkout_execution_jobs', 'SELECT'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'INSERT'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'UPDATE'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'DELETE'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'TRUNCATE'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'REFERENCES'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'TRIGGER'),
                   has_table_privilege(:worker_role, 'checkout_execution_jobs', 'MAINTAIN')
        """), {"worker_role": worker_role}).one()
        assert tuple(worker_table_privileges) == (False, False, False, False, False, False, False, False)
        assert conn.execute(text("""
            SELECT has_table_privilege(:worker_role, 'ola_schema_migrations', 'SELECT')
        """), {"worker_role": worker_role}).scalar_one() is False

    tenant_id = str(uuid.uuid4())
    order_ids = [str(uuid.uuid4()) for _ in range(4)]
    job_ids = [str(uuid.uuid4()) for _ in range(4)]
    stale_queued_token = str(uuid.uuid4())
    stale_running_token = str(uuid.uuid4())
    with migration_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:id, 'worker-claim-test')"),
            {"id": tenant_id},
        )
        conn.execute(text("""
            INSERT INTO checkout_orders
                (id, tenant_id, idempotency_key_hash, request_hash, status, created_at)
            VALUES
                (:id0, :tenant_id, :idem0, :request_hash, 'CHECKOUT_CREATED', 1),
                (:id1, :tenant_id, :idem1, :request_hash, 'CHECKOUT_CREATED', 1),
                (:id2, :tenant_id, :idem2, :request_hash, 'CHECKOUT_CREATED', 1),
                (:id3, :tenant_id, :idem3, :request_hash, 'CHECKOUT_CREATED', 1)
        """), {
            "tenant_id": tenant_id, "request_hash": "a" * 64,
            **{f"id{i}": order_ids[i] for i in range(4)},
            **{f"idem{i}": uuid.uuid4().hex for i in range(4)},
        })
        conn.execute(text("""
            INSERT INTO checkout_execution_jobs
                (id, tenant_id, order_id, approval_record_hash, task, status,
                 attempt_count, claim_token, claimed_at, started_at, created_at)
            VALUES
                (:fresh_id, :tenant_id, :fresh_order, :hash, 'fresh task',
                 'QUEUED', 0, NULL, NULL, NULL, 1),
                (:stale_queued_id, :tenant_id, :stale_queued_order, :hash, 'stale queued task',
                 'QUEUED', 0, :stale_queued_token, 1, NULL, 2),
                (:stale_running_id, :tenant_id, :stale_running_order, :hash, 'stale running task',
                 'RUNNING', 1, :stale_running_token, 1, 1, 3),
                (:attempted_queued_id, :tenant_id, :attempted_queued_order, :hash, 'already attempted queued task',
                 'QUEUED', 1, NULL, NULL, NULL, 4)
        """), {
            "tenant_id": tenant_id, "hash": "b" * 64,
            "fresh_id": job_ids[0], "fresh_order": order_ids[0],
            "stale_queued_id": job_ids[1], "stale_queued_order": order_ids[1],
            "stale_running_id": job_ids[2], "stale_running_order": order_ids[2],
            "attempted_queued_id": job_ids[3], "attempted_queued_order": order_ids[3],
            "stale_queued_token": stale_queued_token,
            "stale_running_token": stale_running_token,
        })

    worker_url = make_url(POSTGRES_URL).set(
        username=worker_role,
        password="ola_worker_test_only",
    )
    worker_engine = create_engine(
        worker_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        with worker_engine.begin() as conn:
            claims = conn.execute(text("""
                SELECT job_id, tenant_id, claim_token
                FROM ola_claim_checkout_jobs(:limit, :stale_after)
            """), {"limit": 10, "stale_after": 900}).all()
        by_id = {row.job_id: row for row in claims}
        assert set(by_id) == set(job_ids[:2])
        assert job_ids[2] not in by_id, "stale RUNNING jobs require manual reconciliation"
        assert job_ids[3] not in by_id, "queued jobs with prior attempts must not be claimed"
        assert all(row.tenant_id == tenant_id for row in claims)
        assert all(len(row.claim_token) == 36 for row in claims)
        assert by_id[job_ids[1]].claim_token != stale_queued_token

        # A stale RUNNING job is left untouched: no automatic takeover is safe
        # without a heartbeat/cancellation protocol for a possibly live executor.
        with migration_engine.begin() as conn:
            stale_running = conn.execute(text("""
                SELECT status, claim_token, claimed_at, started_at
                FROM checkout_execution_jobs WHERE id = :job_id
            """), {"job_id": job_ids[2]}).one()
        assert tuple(stale_running) == ("RUNNING", stale_running_token, 1, 1)

        # A live claim lease prevents a second worker from receiving the job.
        with worker_engine.begin() as conn:
            assert conn.execute(text("""
                SELECT count(*) FROM ola_claim_checkout_jobs(:limit, :stale_after)
            """), {"limit": 10, "stale_after": 900}).scalar_one() == 0

        # The worker role cannot inspect or mutate the outbox directly.
        with worker_engine.begin() as conn:
            with pytest.raises(DBAPIError, match="permission denied"):
                conn.execute(text("SELECT id FROM checkout_execution_jobs")).all()
    finally:
        worker_engine.dispose()


def test_postgres_rls_isolates_tenant_rows_and_preserves_secure_api_key_lookup(postgres_db):
    database, runtime_engine, migration_engine, _admin_engine, runtime_role, _schema, worker_role = postgres_db

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
                INSERT INTO checkout_order_controls (id, order_id, tenant_id, requester_id, status, created_at)
                VALUES (:id, :order_id, :tenant_b, :requester_id, 'PENDING', 0)
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
                    "checkout_order_controls": "(id, order_id, tenant_id, requester_id, status, created_at)",
                    "checkout_execution_jobs": "(id, tenant_id, order_id, approval_record_hash, task, status, attempt_count, created_at)",
                    "checkout_report_reviews": "(id, order_id, tenant_id, reviewer_id, status, report_sha256, reviewed_tip_hash, reason, reviewed_at)",
                }
                values = {
                    "evidence_records": "(:id, :tenant_b, 1, 'probe', '{}', :genesis, :digest)",
                    "stripe_events": "(:id, :tenant_b, :event_id, 'PROCESSING')",
                    "checkout_orders": "(:id, :tenant_b, :idem, :request_hash, 'CHECKOUT_CREATED', 0)",
                    "checkout_order_controls": "(:id, :order_id_control, :tenant_b, :requester_id, 'PENDING', 0)",
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
                try:
                    with pytest.raises(DBAPIError) as exc_info:
                        db.execute(
                            text(f"INSERT INTO {table_name} {insert_columns[table_name]} VALUES {values[table_name]}"),
                            params,
                        )
                    # SQLSTATE 42501 plus PostgreSQL's RLS-specific diagnostic
                    # proves the policy rejected the write, not NOT NULL/FK/UNIQUE.
                    assert getattr(exc_info.value.orig, "sqlstate", None) == "42501", (
                        table_name, exc_info.value.orig,
                    )
                    assert "row-level security policy" in str(exc_info.value.orig).lower(), (
                        table_name, exc_info.value.orig,
                    )
                finally:
                    # PostgreSQL marks the transaction failed after a rejected
                    # RLS write; roll it back before testing the next relation.
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
        database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "REVOKE EXECUTE ON FUNCTION ola_authenticate_api_key(text) FROM PUBLIC"
        )
    database.verify_postgres_schema(runtime_engine, runtime_role=runtime_role, worker_role=worker_role)

    with database.SessionLocal() as db:
        authenticated = db.execute(
            text("SELECT tenant_id, api_key_id, role FROM ola_authenticate_api_key(:key_hash)"),
            {"key_hash": key_b},
        ).one()
    assert authenticated.tenant_id == tenant_b
    assert authenticated.role == "tenant"


def test_postgres_runtime_and_worker_roles_reject_membership_and_inherit(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, _schema, worker_role = postgres_db

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'GRANT "{runtime_role}" TO "{worker_role}"')
    with pytest.raises(RuntimeError, match="must not participate in any role membership"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'REVOKE "{runtime_role}" FROM "{worker_role}"')
        conn.exec_driver_sql(f'ALTER ROLE "{worker_role}" INHERIT')
    with pytest.raises(RuntimeError, match="must be LOGIN, NOINHERIT"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER ROLE "{worker_role}" NOINHERIT')
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )

    outsider_role = "ola_outsider_" + uuid.uuid4().hex[:12]
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE ROLE "{outsider_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
            'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD \'ola_outsider_test_only\''
        )
        conn.exec_driver_sql(f'GRANT "{worker_role}" TO "{outsider_role}"')
    try:
        with pytest.raises(RuntimeError, match="must not participate in any role membership"):
            database.verify_postgres_schema(
                runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
            )
    finally:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'REVOKE "{worker_role}" FROM "{outsider_role}"')
            conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{outsider_role}"')
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )


def test_postgres_worker_dsn_identity_is_verified_and_least_privileged(postgres_db):
    import scripts.run_paid_order_worker as worker

    database, runtime_engine, _migration_engine, _admin_engine, runtime_role, _schema, worker_role = postgres_db
    worker_url = make_url(POSTGRES_URL).set(
        username=worker_role,
        password="ola_worker_test_only",
    )
    worker_engine = create_engine(
        worker_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={_schema}"},
    )

    try:
        worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)

        with _admin_engine.connect() as owner_connection:
            claim_owner = owner_connection.execute(text("""
                SELECT pg_get_userbyid(p.proowner)
                FROM pg_proc AS p
                WHERE p.oid = to_regprocedure(:function_signature)
            """), {
                "function_signature": f"{_schema}.ola_claim_checkout_jobs(integer,integer)",
            }).scalar_one()
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'ALTER FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) OWNER TO "{runtime_role}"'
            )
        with pytest.raises(RuntimeError, match="claim function ACL"):
            worker.verify_worker_database_identity(
                worker_engine, worker_role, runtime_role=runtime_role,
            )
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'ALTER FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) OWNER TO "{claim_owner}"'
            )
            conn.exec_driver_sql(
                f'REVOKE ALL ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) FROM "{worker_role}"'
            )
            conn.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) TO "{worker_role}"'
            )
        worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{_schema}" TO PUBLIC')
        with pytest.raises(RuntimeError, match="worker schema ACL"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{_schema}" FROM PUBLIC')

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT USAGE ON SCHEMA "{_schema}" TO "{worker_role}" WITH GRANT OPTION'
            )
        with pytest.raises(RuntimeError, match="worker schema ACL"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{_schema}" FROM "{worker_role}"')
            conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{_schema}" TO "{worker_role}"')

        schema_outsider = "ola_schema_outsider_" + uuid.uuid4().hex[:10]
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'CREATE ROLE "{schema_outsider}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
                'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD \'ola_schema_outsider_test\''
            )
            conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{_schema}" TO "{schema_outsider}"')
        try:
            with pytest.raises(RuntimeError, match="worker schema ACL"):
                worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        finally:
            with _admin_engine.begin() as conn:
                conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{_schema}" FROM "{schema_outsider}"')
                conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{schema_outsider}"')
        worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION "{_schema}".ola_authenticate_api_key(text) TO "{worker_role}"'
            )
        with pytest.raises(RuntimeError, match="API-key authentication function"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE EXECUTE ON FUNCTION "{_schema}".ola_authenticate_api_key(text) FROM "{worker_role}"'
            )

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) TO PUBLIC'
            )
        with pytest.raises(RuntimeError, match="claim function ACL"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) FROM PUBLIC'
            )

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) TO "{runtime_role}"'
            )
        with pytest.raises(RuntimeError, match="claim function ACL"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) FROM "{runtime_role}"'
            )

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) TO "{worker_role}" WITH GRANT OPTION'
            )
        with pytest.raises(RuntimeError, match="claim function ACL"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE ALL ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) FROM "{worker_role}"'
            )
            conn.exec_driver_sql(
                f'GRANT EXECUTE ON FUNCTION "{_schema}".ola_claim_checkout_jobs(integer, integer) TO "{worker_role}"'
            )

        outsider_role = "ola_worker_outsider_" + uuid.uuid4().hex[:10]
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'CREATE ROLE "{outsider_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
                'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD \'ola_worker_outsider_test\''
            )
            conn.exec_driver_sql(f'GRANT "{worker_role}" TO "{outsider_role}"')
        try:
            with pytest.raises(RuntimeError, match="must not participate in any role membership"):
                worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        finally:
            with _admin_engine.begin() as conn:
                conn.exec_driver_sql(f'REVOKE "{worker_role}" FROM "{outsider_role}"')
                conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{outsider_role}"')
        worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)

        with pytest.raises(RuntimeError, match="identity mismatch"):
            worker.verify_worker_database_identity(runtime_engine, worker_role, runtime_role=runtime_role)

        # An administrator that uses SET ROLE must not masquerade as a worker
        # DSN: current_user changes, but session_user remains the administrator.
        admin_as_worker_engine = create_engine(
            POSTGRES_URL,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={_schema}"},
        )

        @event.listens_for(admin_as_worker_engine, "connect")
        def assume_worker_from_admin(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET ROLE "{worker_role}"')
            cursor.close()
            dbapi_connection.commit()

        try:
            with pytest.raises(RuntimeError, match="session identity mismatch"):
                worker.verify_worker_database_identity(admin_as_worker_engine, worker_role, runtime_role=runtime_role)
        finally:
            admin_as_worker_engine.dispose()

        # The API's runtime role is subject to the same authenticated-session
        # check, not merely current_user after an administrative SET ROLE.
        admin_as_runtime_engine = create_engine(
            POSTGRES_URL,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={_schema}"},
        )

        @event.listens_for(admin_as_runtime_engine, "connect")
        def assume_runtime_from_admin(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET ROLE "{runtime_role}"')
            cursor.close()
            dbapi_connection.commit()

        try:
            with pytest.raises(RuntimeError, match="current_user and session_user"):
                database.verify_postgres_schema(
                    admin_as_runtime_engine,
                    runtime_role=runtime_role,
                    worker_role=worker_role,
                )
        finally:
            admin_as_runtime_engine.dispose()
        with pytest.raises(RuntimeError, match="identity mismatch"):
            worker.verify_worker_database_identity(_admin_engine, worker_role, runtime_role=runtime_role)

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT SELECT ON TABLE "{_schema}".checkout_execution_jobs TO "{worker_role}"'
            )
        with pytest.raises(RuntimeError, match="direct privileges"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE SELECT ON TABLE "{_schema}".checkout_execution_jobs FROM "{worker_role}"'
            )

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT MAINTAIN ON TABLE "{_schema}".checkout_execution_jobs TO "{worker_role}"'
            )
        with pytest.raises(RuntimeError, match="direct privileges"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE MAINTAIN ON TABLE "{_schema}".checkout_execution_jobs FROM "{worker_role}"'
            )

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'GRANT SELECT ON TABLE "{_schema}".ola_schema_migrations TO "{worker_role}"'
            )
        with pytest.raises(RuntimeError, match="direct privileges"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE SELECT ON TABLE "{_schema}".ola_schema_migrations FROM "{worker_role}"'
            )

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'GRANT CREATE ON SCHEMA "{_schema}" TO "{worker_role}"')
        with pytest.raises(RuntimeError, match="schema USAGE"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'REVOKE CREATE ON SCHEMA "{_schema}" FROM "{worker_role}"')

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER ROLE "{worker_role}" INHERIT')
        with pytest.raises(RuntimeError, match="must be LOGIN NOINHERIT"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER ROLE "{worker_role}" NOINHERIT')

        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'GRANT "{runtime_role}" TO "{worker_role}"')
        with pytest.raises(RuntimeError, match="must not participate in any role membership"):
            worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
        with _admin_engine.begin() as conn:
            conn.exec_driver_sql(f'REVOKE "{runtime_role}" FROM "{worker_role}"')

        worker.verify_worker_database_identity(worker_engine, worker_role, runtime_role=runtime_role)
    finally:
        worker_engine.dispose()


def test_postgres_runtime_role_rejects_extra_table_grants(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema, worker_role = postgres_db

    # Migration grants are installed by migrate_postgres_schema itself; no
    # fixture-side GRANT is allowed to make the runtime role appear valid.
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT DELETE ON TABLE "{schema}".checkout_orders TO "{runtime_role}"'
        )
    with pytest.raises(RuntimeError, match="runtime role table grants are not least-privilege: checkout_orders"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE DELETE ON TABLE "{schema}".checkout_orders FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT SELECT ON TABLE "{schema}".checkout_orders TO PUBLIC'
        )
    with pytest.raises(RuntimeError, match="runtime table ACL is not least-privilege: checkout_orders"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE SELECT ON TABLE "{schema}".checkout_orders FROM PUBLIC'
        )

    extra_role = "ola_runtime_acl_" + uuid.uuid4().hex[:10]
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE ROLE "{extra_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
            'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD \'ola_runtime_acl_test\''
        )
        conn.exec_driver_sql(
            f'GRANT SELECT ON TABLE "{schema}".checkout_orders TO "{extra_role}"'
        )
    try:
        with pytest.raises(RuntimeError, match="runtime table ACL is not least-privilege: checkout_orders"):
            database.verify_postgres_schema(
                runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
            )
    finally:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'REVOKE SELECT ON TABLE "{schema}".checkout_orders FROM "{extra_role}"'
            )
            conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{extra_role}"')

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT SELECT ON TABLE "{schema}".checkout_orders TO "{runtime_role}" WITH GRANT OPTION'
        )
    with pytest.raises(RuntimeError, match="runtime table ACL is not least-privilege: checkout_orders"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE GRANT OPTION FOR SELECT ON TABLE "{schema}".checkout_orders FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )


def test_postgres_migration_reconciles_unexpected_function_execute_grants(postgres_db):
    database, _runtime_engine, migration_engine, admin_engine, runtime_role, schema, worker_role = postgres_db
    extra_role = "ola_acl_extra_" + uuid.uuid4().hex[:10]
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE ROLE "{extra_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
            'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD \'ola_acl_extra_test\''
        )
        conn.exec_driver_sql(
            f'GRANT EXECUTE ON FUNCTION "{schema}".ola_authenticate_api_key(text) TO "{extra_role}"'
        )
        conn.exec_driver_sql(
            f'GRANT EXECUTE ON FUNCTION "{schema}".ola_claim_checkout_jobs(integer, integer) TO "{extra_role}"'
        )
        conn.exec_driver_sql(
            f'GRANT EXECUTE ON FUNCTION "{schema}".ola_authenticate_api_key(text) TO "{runtime_role}" WITH GRANT OPTION'
        )
        conn.exec_driver_sql(
            f'GRANT EXECUTE ON FUNCTION "{schema}".ola_claim_checkout_jobs(integer, integer) TO "{worker_role}" WITH GRANT OPTION'
        )
        conn.exec_driver_sql(
            f'GRANT SELECT ON TABLE "{schema}".checkout_orders TO "{extra_role}"'
        )
        conn.exec_driver_sql(
            f'GRANT SELECT ON TABLE "{schema}".checkout_orders TO PUBLIC'
        )
        conn.exec_driver_sql(
            f'GRANT SELECT ON TABLE "{schema}".checkout_orders TO "{runtime_role}" WITH GRANT OPTION'
        )
        conn.exec_driver_sql(
            f'GRANT CREATE ON SCHEMA "{schema}" TO PUBLIC'
        )
        conn.exec_driver_sql(
            f'GRANT USAGE ON SCHEMA "{schema}" TO "{extra_role}"'
        )
        conn.exec_driver_sql(
            f'GRANT USAGE ON SCHEMA "{schema}" TO "{runtime_role}" WITH GRANT OPTION'
        )
        conn.exec_driver_sql(
            f'GRANT USAGE ON SCHEMA "{schema}" TO "{worker_role}" WITH GRANT OPTION'
        )

    try:
        database.migrate_postgres_schema(
            migration_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
        with admin_engine.begin() as conn:
            assert conn.execute(text("""
                SELECT has_function_privilege(
                    :extra_role,
                    to_regprocedure(:auth_function),
                    'EXECUTE'
                )
            """), {
                "extra_role": extra_role,
                "auth_function": f"{schema}.ola_authenticate_api_key(text)",
            }).scalar_one() is False
            assert conn.execute(text("""
                SELECT has_function_privilege(
                    :extra_role,
                    to_regprocedure(:claim_function),
                    'EXECUTE'
                )
            """), {
                "extra_role": extra_role,
                "claim_function": f"{schema}.ola_claim_checkout_jobs(integer,integer)",
            }).scalar_one() is False
            assert conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_proc AS p
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(p.proacl, acldefault('f', p.proowner))
                    ) AS acl
                    WHERE p.oid = to_regprocedure(:auth_function)
                      AND acl.privilege_type = 'EXECUTE'
                      AND acl.grantee = pg_catalog.to_regrole(:runtime_role)::oid
                      AND acl.is_grantable
                )
            """), {
                "auth_function": f"{schema}.ola_authenticate_api_key(text)",
                "runtime_role": runtime_role,
            }).scalar_one() is False
            assert conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_proc AS p
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(p.proacl, acldefault('f', p.proowner))
                    ) AS acl
                    WHERE p.oid = to_regprocedure(:claim_function)
                      AND acl.privilege_type = 'EXECUTE'
                      AND acl.grantee = pg_catalog.to_regrole(:worker_role)::oid
                      AND acl.is_grantable
                )
            """), {
                "claim_function": f"{schema}.ola_claim_checkout_jobs(integer,integer)",
                "worker_role": worker_role,
            }).scalar_one() is False
            table_acl = conn.execute(text("""
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM pg_class AS c
                        JOIN pg_namespace AS n ON n.oid = c.relnamespace
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(c.relacl, acldefault('r', c.relowner))
                        ) AS acl
                        WHERE n.nspname = :schema_name
                          AND c.relname = 'checkout_orders'
                          AND acl.grantee = 0
                    ) AS public_grant,
                    EXISTS (
                        SELECT 1
                        FROM pg_class AS c
                        JOIN pg_namespace AS n ON n.oid = c.relnamespace
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(c.relacl, acldefault('r', c.relowner))
                        ) AS acl
                        WHERE n.nspname = :schema_name
                          AND c.relname = 'checkout_orders'
                          AND acl.grantee = pg_catalog.to_regrole(:extra_role)::oid
                    ) AS extra_role_grant,
                    EXISTS (
                        SELECT 1
                        FROM pg_class AS c
                        JOIN pg_namespace AS n ON n.oid = c.relnamespace
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(c.relacl, acldefault('r', c.relowner))
                        ) AS acl
                        WHERE n.nspname = :schema_name
                          AND c.relname = 'checkout_orders'
                          AND acl.grantee = pg_catalog.to_regrole(:runtime_role)::oid
                          AND acl.is_grantable
                    ) AS runtime_grant_option
            """), {
                "schema_name": schema,
                "extra_role": extra_role,
                "runtime_role": runtime_role,
            }).one()
            assert tuple(table_acl) == (False, False, False)
            schema_acl = conn.execute(text("""
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM pg_namespace AS n
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(n.nspacl, acldefault('n', n.nspowner))
                        ) AS acl
                        WHERE n.nspname = :schema_name
                          AND acl.grantee = 0
                    ) AS public_acl,
                    EXISTS (
                        SELECT 1
                        FROM pg_namespace AS n
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(n.nspacl, acldefault('n', n.nspowner))
                        ) AS acl
                        WHERE n.nspname = :schema_name
                          AND acl.grantee = pg_catalog.to_regrole(:extra_role)::oid
                    ) AS extra_role_acl,
                    EXISTS (
                        SELECT 1
                        FROM pg_namespace AS n
                        CROSS JOIN LATERAL aclexplode(
                            COALESCE(n.nspacl, acldefault('n', n.nspowner))
                        ) AS acl
                        WHERE n.nspname = :schema_name
                          AND acl.grantee IN (
                              pg_catalog.to_regrole(:runtime_role)::oid,
                              pg_catalog.to_regrole(:worker_role)::oid
                          )
                          AND acl.is_grantable
                    ) AS application_grant_option
            """), {
                "schema_name": schema,
                "extra_role": extra_role,
                "runtime_role": runtime_role,
                "worker_role": worker_role,
            }).one()
            assert tuple(schema_acl) == (False, False, False)
        database.verify_postgres_schema(
            _runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    finally:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'DROP OWNED BY "{extra_role}"')
            conn.exec_driver_sql(f'DROP ROLE IF EXISTS "{extra_role}"')


def test_postgres_runtime_verifier_rejects_nonleast_privilege_schema_acl(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema, worker_role = postgres_db

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO PUBLIC')
    with pytest.raises(RuntimeError, match="schema ACL is not least-privilege"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')

    outsider_role = "ola_runtime_schema_" + uuid.uuid4().hex[:10]
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE ROLE "{outsider_role}" LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS '
            'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD \'ola_runtime_schema_test\''
        )
        conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{outsider_role}"')
    try:
        with pytest.raises(RuntimeError, match="schema ACL is not least-privilege"):
            database.verify_postgres_schema(
                runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
            )
    finally:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{outsider_role}"')
            conn.exec_driver_sql(f'DROP ROLE "{outsider_role}"')

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT USAGE ON SCHEMA "{schema}" TO "{runtime_role}" WITH GRANT OPTION'
        )
    with pytest.raises(RuntimeError, match="schema ACL is not least-privilege"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE GRANT OPTION FOR USAGE ON SCHEMA "{schema}" FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )


def test_postgres_runtime_verifier_rejects_force_rls_on_claim_table(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema, worker_role = postgres_db

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'ALTER TABLE "{schema}".checkout_execution_jobs FORCE ROW LEVEL SECURITY'
        )
    with pytest.raises(RuntimeError, match="FORCE ROW LEVEL SECURITY"):
        database.verify_postgres_schema(
            runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
        )
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'ALTER TABLE "{schema}".checkout_execution_jobs NO FORCE ROW LEVEL SECURITY'
        )
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )


@pytest.mark.parametrize(
    ("function_name", "signature"),
    [
        ("ola_authenticate_api_key", "text"),
        ("ola_claim_checkout_jobs", "integer, integer"),
    ],
)
def test_postgres_runtime_verifier_rejects_definer_owner_different_from_table_owner(
    postgres_db, function_name, signature,
):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema, worker_role = postgres_db
    table_name = "api_keys" if function_name == "ola_authenticate_api_key" else "checkout_execution_jobs"
    with admin_engine.connect() as conn:
        original_owner = conn.execute(text("""
            SELECT pg_get_userbyid(c.relowner)
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema_name AND c.relname = :table_name
        """), {"schema_name": schema, "table_name": table_name}).scalar_one()

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'GRANT CREATE ON SCHEMA "{schema}" TO "{runtime_role}"')
        conn.exec_driver_sql(
            f'ALTER FUNCTION "{schema}".{function_name}({signature}) OWNER TO "{runtime_role}"'
        )
    try:
        message = (
            "API-key SECURITY DEFINER owner must match the api_keys table owner"
            if function_name == "ola_authenticate_api_key"
            else "claim SECURITY DEFINER owner must match the checkout_execution_jobs table owner"
        )
        with pytest.raises(RuntimeError, match=message):
            database.verify_postgres_schema(
                runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
            )
    finally:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(
                f'ALTER FUNCTION "{schema}".{function_name}({signature}) OWNER TO "{original_owner}"'
            )
            conn.exec_driver_sql(f'REVOKE CREATE ON SCHEMA "{schema}" FROM "{runtime_role}"')
    database.verify_postgres_schema(
        runtime_engine, runtime_role=runtime_role, worker_role=worker_role,
    )
