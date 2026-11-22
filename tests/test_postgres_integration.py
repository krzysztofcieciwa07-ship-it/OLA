"""Real PostgreSQL tests. Set OLA_TEST_POSTGRES_URL to enable them."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select
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
            # Human Gate membership is managed out-of-band; runtime must read only.
            conn.exec_driver_sql(
                f'REVOKE ALL ON TABLE "{schema}".human_gate_memberships FROM "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'GRANT SELECT ON TABLE "{schema}".human_gate_memberships TO "{runtime_role}"'
            )
            # Approval nonces are append-only: runtime may read/insert, never mutate/delete.
            conn.exec_driver_sql(
                f'REVOKE ALL ON TABLE "{schema}".human_gate_approval_nonce_ledger FROM "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'GRANT SELECT, INSERT ON TABLE "{schema}".human_gate_approval_nonce_ledger TO "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'REVOKE ALL ON TABLE "{schema}".ola_schema_migrations FROM "{runtime_role}"'
            )
            conn.exec_driver_sql(
                f'GRANT SELECT ON TABLE "{schema}".ola_schema_migrations TO "{runtime_role}"'
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
    from app.igor_evidence_verifier import verify_chain
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




def test_postgres_membership_rls_verifier_rejects_extra_permissive_policy(postgres_db):
    database, runtime_engine, migration_engine, _admin_engine, _runtime_role, _schema = postgres_db

    with migration_engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE POLICY human_gate_memberships_unrestricted_test
            ON human_gate_memberships
            FOR SELECT
            USING (true)
        """)

    with pytest.raises(RuntimeError, match="missing, duplicated or semantically invalid"):
        database.verify_postgres_schema(runtime_engine)

    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "DROP POLICY human_gate_memberships_unrestricted_test ON human_gate_memberships"
        )
    database.verify_postgres_schema(runtime_engine)


def test_postgres_membership_rls_verifier_rejects_bypassrls_runtime_role(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, _schema = postgres_db

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER ROLE "{runtime_role}" BYPASSRLS')

    try:
        with pytest.raises(RuntimeError, match="must not own the table or bypass RLS"):
            database.verify_postgres_schema(runtime_engine)
    finally:
        with admin_engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER ROLE "{runtime_role}" NOBYPASSRLS')

    database.verify_postgres_schema(runtime_engine)

def test_postgres_membership_rls_is_tenant_scoped_and_transaction_local(postgres_db):
    from sqlalchemy import select, text
    from app.models import HumanGateMembership, Tenant

    database, _runtime_engine, migration_engine, _admin_engine, _runtime_role, _schema = postgres_db
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    principal_a = str(uuid.uuid4())
    principal_b = str(uuid.uuid4())

    with migration_engine.begin() as conn:
        conn.execute(
            Tenant.__table__.insert(),
            [
                {"id": tenant_a, "name": "RLS tenant A"},
                {"id": tenant_b, "name": "RLS tenant B"},
            ],
        )
        for tenant_id, principal_id, tenant_suffix, fingerprint in (
            (tenant_a, principal_a, "a", "a" * 64),
            (tenant_b, principal_b, "b", "b" * 64),
        ):
            # Even an out-of-band administrator/owner must scope writes when
            # FORCE ROW LEVEL SECURITY is enabled on the membership table.
            conn.execute(
                text("SELECT set_config('ola.human_gate_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            conn.execute(
                HumanGateMembership.__table__.insert(),
                {
                    "id": principal_id,
                    "tenant_id": tenant_id,
                    "issuer": f"https://issuer.example.test/tenant-{tenant_suffix}",
                    "subject_fingerprint": fingerprint,
                    "fingerprint_key_id": "identity-k1",
                    "role": "execution_approver",
                    "membership_version": 1,
                    "active": True,
                    "revoked_at": None,
                    "created_at": 1795318200,
                },
            )

    with database.SessionLocal() as db:
        # No transaction-local tenant context must fail closed to zero rows.
        assert db.scalars(select(HumanGateMembership)).all() == []

        database.set_human_gate_tenant_scope(db, tenant_a)
        with pytest.raises(RuntimeError, match="cannot change within the same transaction"):
            database.set_human_gate_tenant_scope(db, tenant_b)
        rows_a = db.scalars(select(HumanGateMembership)).all()
        assert [row.id for row in rows_a] == [principal_a]
        db.commit()

        # SET LOCAL semantics: context must not leak into a fresh transaction.
        assert db.scalars(select(HumanGateMembership)).all() == []
        database.set_human_gate_tenant_scope(db, tenant_b)
        rows_b = db.scalars(select(HumanGateMembership)).all()
        assert [row.id for row in rows_b] == [principal_b]
        db.commit()

        # A second tenant context cannot read tenant A by primary key either.
        db.expunge_all()
        database.set_human_gate_tenant_scope(db, tenant_b)
        assert db.get(HumanGateMembership, principal_a) is None



def test_postgres_runtime_rejects_write_access_to_human_gate_memberships(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema = postgres_db

    # Membership rows are administered out-of-band; runtime must be SELECT-only.
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT INSERT ON TABLE "{schema}".human_gate_memberships TO "{runtime_role}"'
        )
    with pytest.raises(RuntimeError, match="Human Gate membership table must be read-only"):
        database.verify_postgres_schema(runtime_engine)

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE INSERT ON TABLE "{schema}".human_gate_memberships FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(runtime_engine)


def test_postgres_schema_fails_closed_when_human_gate_approval_nonce_ledger_is_missing(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, _runtime_role, schema = postgres_db

    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'DROP TABLE IF EXISTS "{schema}".human_gate_approval_nonce_ledger CASCADE'
        )

    with pytest.raises(RuntimeError, match="human_gate_approval_nonce_ledger"):
        database.verify_postgres_schema(runtime_engine)



def test_postgres_human_gate_approval_nonce_is_atomic_append_only_and_tenant_scoped(postgres_db):
    database, runtime_engine, migration_engine, admin_engine, runtime_role, schema = postgres_db
    from app.approval_nonce_ledger import (
        ApprovalNonceReplayError,
        PostgresApprovalNonceLedger,
    )
    from app.models import HumanGateApprovalNonce, Tenant

    tenant_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())
    nonce = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    envelope_sha256 = "a" * 64
    now = 1795318200
    ledger = PostgresApprovalNonceLedger()

    with database.SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Human Gate approval nonce tenant"))
        db.commit()

    def consume_once(_index):
        with database.SessionLocal() as db:
            try:
                row_id = ledger.consume(
                    db,
                    tenant_id=tenant_id,
                    approval_id=approval_id,
                    nonce=nonce,
                    operation_id=operation_id,
                    action="EXECUTE_PAID_ORDER",
                    resource_type="checkout_order",
                    resource_id=str(uuid.uuid4()),
                    envelope_sha256=envelope_sha256,
                    consumed_at=now,
                )
                db.commit()
                return ("consumed", row_id)
            except ApprovalNonceReplayError:
                db.rollback()
                return ("replay", None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(consume_once, range(8)))

    consumed = [item for item in outcomes if item[0] == "consumed"]
    replayed = [item for item in outcomes if item[0] == "replay"]
    assert len(consumed) == 1
    assert len(replayed) == 7

    with database.SessionLocal() as db:
        rows = db.scalars(
            select(HumanGateApprovalNonce).where(
                HumanGateApprovalNonce.tenant_id == tenant_id
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].approval_id == approval_id
        assert rows[0].nonce == nonce
        assert rows[0].operation_id == operation_id
        assert rows[0].envelope_sha256 == envelope_sha256

    # Either one-use key is sufficient to reject another consumption.
    with database.SessionLocal() as db:
        with pytest.raises(ApprovalNonceReplayError):
            ledger.consume(
                db, tenant_id=tenant_id, approval_id=approval_id,
                nonce=str(uuid.uuid4()), operation_id=str(uuid.uuid4()),
                action="EXECUTE_PAID_ORDER", resource_type="checkout_order",
                resource_id=str(uuid.uuid4()), envelope_sha256=envelope_sha256,
                consumed_at=now + 1,
            )
        db.rollback()
    with database.SessionLocal() as db:
        with pytest.raises(ApprovalNonceReplayError):
            ledger.consume(
                db, tenant_id=tenant_id, approval_id=str(uuid.uuid4()),
                nonce=nonce, operation_id=str(uuid.uuid4()),
                action="EXECUTE_PAID_ORDER", resource_type="checkout_order",
                resource_id=str(uuid.uuid4()), envelope_sha256=envelope_sha256,
                consumed_at=now + 2,
            )
        db.rollback()

    # The database blocks privileged accidental mutation as a second layer.
    with migration_engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.exec_driver_sql(
                'UPDATE human_gate_approval_nonce_ledger SET consumed_at = 1 WHERE tenant_id = %s',
                (tenant_id,),
            )
    with migration_engine.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.exec_driver_sql(
                'DELETE FROM human_gate_approval_nonce_ledger WHERE tenant_id = %s',
                (tenant_id,),
            )

    database.verify_postgres_schema(runtime_engine)
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'GRANT UPDATE, DELETE, TRUNCATE ON TABLE "{schema}".human_gate_approval_nonce_ledger TO "{runtime_role}"'
        )
    with pytest.raises(RuntimeError, match="Human Gate approval nonce ledger requires SELECT/INSERT only"):
        database.verify_postgres_schema(runtime_engine)
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(
            f'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE "{schema}".human_gate_approval_nonce_ledger FROM "{runtime_role}"'
        )
    database.verify_postgres_schema(runtime_engine)


def test_human_gate_approval_nonce_ledger_fails_closed_without_postgresql():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.approval_nonce_ledger import (
        ApprovalNonceLedgerUnavailable,
        PostgresApprovalNonceLedger,
    )

    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as db:
            with pytest.raises(ApprovalNonceLedgerUnavailable, match="requires PostgreSQL"):
                PostgresApprovalNonceLedger().consume(
                    db,
                    tenant_id=str(uuid.uuid4()),
                    approval_id=str(uuid.uuid4()),
                    nonce=str(uuid.uuid4()),
                    operation_id=str(uuid.uuid4()),
                    action="EXECUTE_PAID_ORDER",
                    resource_type="checkout_order",
                    resource_id=str(uuid.uuid4()),
                    envelope_sha256="b" * 64,
                    consumed_at=1795318200,
                )
    finally:
        engine.dispose()
