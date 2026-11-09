"""Real PostgreSQL tests. Set OLA_TEST_POSTGRES_URL to enable them."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

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
        database.migrate_postgres_schema(migration_engine)
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{runtime_role}"')
            conn.exec_driver_sql(
                f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "{schema}" TO "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'REVOKE UPDATE, DELETE ON TABLE "{schema}".evidence_records FROM "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'REVOKE ALL ON TABLE "{schema}".ola_schema_migrations FROM "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'GRANT SELECT ON TABLE "{schema}".ola_schema_migrations TO "{runtime_role}"'
            )
            # The online nonce writer only inserts. No read or destructive
            # permissions are required for the replay boundary.
            conn.exec_driver_sql(
                f'REVOKE SELECT, UPDATE, DELETE, TRUNCATE ON TABLE "{schema}".secure_bridge_nonces FROM "{runtime_role}"'
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
    with database.SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="PostgreSQL integration tenant"))
        db.commit()

    def append_event(index):
        return database.append_evidence_atomic(
            tenant_id, "integration.append", {"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(append_event, range(32)))

    assert len({item["id"] for item in results}) == 32
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



def test_postgres_nonce_reservation_works_without_runtime_delete_privilege(postgres_db, monkeypatch):
    database, _runtime_engine, _migration_engine, _admin_engine, _runtime_role, _schema = postgres_db
    from app import secure_bridge

    # The application runtime role is deliberately not granted DELETE on the
    # nonce table. Expired nonce cleanup belongs to the separate maintenance role.
    monkeypatch.setattr(secure_bridge, "SessionLocal", database.SessionLocal)
    nonce = "a" * 64

    secure_bridge.consume_nonce(
        key_id="bridge-runtime-role-test",
        nonce=nonce,
        retention_seconds=180,
    )
    with pytest.raises(secure_bridge.SecureBridgeNonceReplay):
        secure_bridge.consume_nonce(
            key_id="bridge-runtime-role-test",
            nonce=nonce,
            retention_seconds=180,
        )



def test_postgres_nonce_reservation_works_without_runtime_delete_privilege(postgres_db, monkeypatch):
    database, runtime_engine, _migration_engine, _admin_engine, _runtime_role, _schema = postgres_db
    from app import secure_bridge

    # The runtime role has INSERT-only access to nonce state.
    monkeypatch.setattr(secure_bridge, "SessionLocal", database.SessionLocal)
    nonce = "a" * 64

    secure_bridge.consume_nonce(
        key_id="bridge-runtime-role-test",
        nonce=nonce,
        retention_seconds=180,
    )
    with pytest.raises(secure_bridge.SecureBridgeNonceReplay):
        secure_bridge.consume_nonce(
            key_id="bridge-runtime-role-test",
            nonce=nonce,
            retention_seconds=180,
        )
    database.verify_postgres_schema(runtime_engine)


def test_postgres_runtime_rejects_delete_privilege_on_nonce_ledger(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema = postgres_db

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT DELETE ON TABLE "{schema}".secure_bridge_nonces TO "{runtime_role}"'
        )
    with pytest.raises(RuntimeError, match="INSERT only on secure_bridge_nonces"):
        database.verify_postgres_schema(runtime_engine)
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE DELETE ON TABLE "{schema}".secure_bridge_nonces FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(runtime_engine)


def test_expired_nonce_pruning_uses_maintenance_engine_only(postgres_db, monkeypatch):
    database, _runtime_engine, migration_engine, _admin_engine, _runtime_role, _schema = postgres_db
    from app import secure_bridge
    from app.models import SecureBridgeNonce

    monkeypatch.setattr(secure_bridge, "SessionLocal", database.SessionLocal)
    secure_bridge.consume_nonce(
        key_id="bridge-maintenance-test",
        nonce="b" * 64,
        retention_seconds=60,
        now=1000,
    )
    secure_bridge.consume_nonce(
        key_id="bridge-maintenance-test",
        nonce="c" * 64,
        retention_seconds=60,
        now=1950,
    )

    assert secure_bridge.prune_expired_nonces(migration_engine, now=2000) == 1
    with migration_engine.connect() as conn:
        remaining = conn.execute(
            select(func.count()).select_from(SecureBridgeNonce)
        ).scalar_one()
    assert remaining == 1
