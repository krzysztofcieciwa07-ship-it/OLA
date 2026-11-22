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


def test_postgres_membership_revocation_waits_for_runtime_authorization_lock(postgres_db):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import text
    from app import database
    from app.models import Tenant

    database, runtime_engine, _migration_engine, admin_engine, _runtime_role, schema = postgres_db
    tenant_id = str(uuid.uuid4())
    principal_id = str(uuid.uuid4())
    with database.SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Membership revocation serialization tenant"))
        db.commit()

    with admin_engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('ola.human_gate_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        conn.execute(text(f'''
            INSERT INTO "{schema}".human_gate_memberships
                (id, tenant_id, issuer, subject_fingerprint, fingerprint_key_id,
                 role, membership_version, active, revoked_at, created_at)
            VALUES
                (:id, :tenant_id, :issuer, :fingerprint, :key_id,
                 'execution_approver', 1, TRUE, NULL, 1795318200)
        '''), {
            "id": principal_id,
            "tenant_id": tenant_id,
            "issuer": "https://issuer.example.test/tenant",
            "fingerprint": "a" * 64,
            "key_id": "identity-k1",
        })

    lock_acquired = threading.Event()
    release_lock = threading.Event()
    update_started = threading.Event()
    application_name = "ola_hg_membership_revoke_test"

    def hold_runtime_authorization_lock():
        with database.SessionLocal() as db:
            database.set_human_gate_tenant_scope(db, tenant_id)
            database.lock_tenant_human_gate_memberships(db, tenant_id)
            active = db.execute(text(
                "SELECT active FROM human_gate_memberships WHERE id = :principal_id"
            ), {"principal_id": principal_id}).scalar_one()
            assert active is True
            lock_acquired.set()
            assert release_lock.wait(timeout=10), "test did not release runtime transaction"
            db.commit()

    def revoke_membership():
        assert lock_acquired.wait(timeout=5), "runtime did not acquire membership lock"
        with admin_engine.connect() as conn:
            conn.exec_driver_sql(f"SET application_name = '{application_name}'")
            conn.commit()
            update_started.set()
            with conn.begin():
                conn.execute(
                    text("SELECT set_config('ola.human_gate_tenant_id', :tenant_id, true)"),
                    {"tenant_id": tenant_id},
                )
                conn.execute(text(f'''
                    UPDATE "{schema}".human_gate_memberships
                    SET active = FALSE, revoked_at = 1795318201, membership_version = 2
                    WHERE id = :principal_id
                '''), {"principal_id": principal_id})

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker_future = pool.submit(hold_runtime_authorization_lock)
        assert lock_acquired.wait(timeout=5), "runtime membership lock was not acquired"
        revoke_future = pool.submit(revoke_membership)
        assert update_started.wait(timeout=5), "revocation transaction did not start"

        # Prove PostgreSQL reached the trigger and is blocked on the advisory lock;
        # do not infer blocking from a short sleep or unscheduled Python thread.
        deadline = time.monotonic() + 5
        observed_wait = False
        while time.monotonic() < deadline:
            with admin_engine.connect() as observer:
                observed_wait = observer.execute(text("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_stat_activity
                        WHERE application_name = :application_name
                          AND wait_event_type = 'Lock'
                          AND wait_event = 'advisory'
                    )
                """), {"application_name": application_name}).scalar_one()
            if observed_wait:
                break
            time.sleep(0.05)
        assert observed_wait, "revocation did not block on the tenant membership advisory lock"

        release_lock.set()
        worker_future.result(timeout=5)
        revoke_future.result(timeout=5)

    with admin_engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('ola.human_gate_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        row = conn.execute(text(f'''
            SELECT active, membership_version
            FROM "{schema}".human_gate_memberships
            WHERE id = :principal_id
        '''), {"principal_id": principal_id}).one()
    assert row.active is False
    assert row.membership_version == 2


def test_signed_approval_ingress_binds_live_oidc_session_and_queues_once(postgres_db, monkeypatch):
    import base64
    import hashlib
    import json
    import time
    import uuid
    from datetime import datetime, timezone

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import approval_identity, main, database
    from app.api_key_hashing import api_key_fingerprint
    from app.approval_contract_v1 import oidc_subject_fingerprint, signing_input
    from app.models import (
        ApiKey, CheckoutExecutionJob, CheckoutOrder, CheckoutOrderControl,
        EvidenceRecord, HumanGateApprovalNonce, HumanGateMembership, Tenant,
    )
    from app.signed_approval_runtime import signed_envelope_sha256

    database, runtime_engine, migration_engine, _admin_engine, _runtime_role, _schema = postgres_db
    monkeypatch.setattr(main, "SessionLocal", database.SessionLocal)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)

    # Seed parent rows before children: model declarations do not define ORM relationships.
    tenant_id = str(uuid.uuid4())
    requester_id = str(uuid.uuid4())
    approver_id = str(uuid.uuid4())
    requester_key = f"requester-{uuid.uuid4()}"
    approver_key = f"approver-{uuid.uuid4()}"
    order_id = str(uuid.uuid4())
    session_id_value = f"cs_test_{uuid.uuid4().hex}"
    event_id = f"evt_test_{uuid.uuid4().hex}"
    task = "Run the signed PostgreSQL Human Gate ingress integration test."
    request_hash = hashlib.sha256(task.encode()).hexdigest()
    with database.SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="signed-approval-ingress"))
        db.commit()
        db.add_all([
            ApiKey(id=requester_id, tenant_id=tenant_id,
                   key_hash=api_key_fingerprint(requester_key)),
            ApiKey(id=approver_id, tenant_id=tenant_id,
                   key_hash=api_key_fingerprint(approver_key), role="execution_approver"),
        ])
        db.commit()
        db.add(CheckoutOrder(
            id=order_id,
            tenant_id=tenant_id,
            idempotency_key_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
            request_hash=request_hash,
            task=task,
            status="PAID_PENDING_REVIEW",
            stripe_session_id=session_id_value,
            checkout_url="https://checkout.stripe.test/session",
            payment_event_id=event_id,
        ))
        db.add(CheckoutOrderControl(
            id=str(uuid.uuid4()), order_id=order_id, tenant_id=tenant_id,
            requester_id=requester_id, status="PAID_PENDING_REVIEW",
        ))
        db.commit()

    checkout = database.append_evidence_atomic(tenant_id, "stripe.checkout_created", {
        "ola_order_id": order_id,
        "tenant_id": tenant_id,
        "requester_id": requester_id,
        "checkout_session_id": session_id_value,
        "request_hash": request_hash,
    })
    payment = database.append_evidence_atomic(tenant_id, "stripe.payment_confirmed", {
        "ola_order_id": order_id,
        "stripe_event_id": event_id,
        "checkout_session_id": session_id_value,
        "offer": "ola-execution-audit",
        "product": "OLA Execution Audit",
        "amount_total": 9900,
        "currency": "eur",
        "request_hash": request_hash,
        "execution_authorized": False,
        "review_required": True,
    })
    post_payment_tip = database.append_evidence_atomic(
        tenant_id,
        "integration.post_payment_audit_marker",
        {"marker": "challenge-must-bind-current-chain-tip"},
    )
    payment_result = {
        "status": "PAID_PENDING_REVIEW",
        "event_id": event_id,
        "order_id": order_id,
        "checkout_session_id": session_id_value,
        "payment": "CONFIRMED",
        "ola_status": "NOT_STARTED",
        "ola_run_id": None,
        "payment_evidence_id": payment["id"],
        "execution_authorized": False,
        "next_gate": "HUMAN_REVIEW",
    }
    with database.SessionLocal() as db:
        order_row = db.get(CheckoutOrder, order_id)
        order_row.payment_result_json = json.dumps(payment_result)
        control_row = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == order_id
        ))
        control_row.payment_evidence_id = payment["id"]
        db.commit()
        tip_hash = db.scalar(select(EvidenceRecord.record_hash).where(
            EvidenceRecord.tenant_id == tenant_id
        ).order_by(EvidenceRecord.seq.desc()))
    ctx = {
        "tenant_id": tenant_id,
        "requester_id": requester_id,
        "approver_id": approver_id,
        "order_id": order_id,
        "session_id": session_id_value,
        "task": task,
        "payment_evidence_id": payment["id"],
        "checkout_evidence_id": checkout["id"],
        "tip_hash": tip_hash,
    }

    issuer = "https://login.example.test/tenant"
    reviewer_subject = f"approver:{ctx['approver_id']}"
    requester_subject = f"requester:{ctx['requester_id']}"
    fingerprint_key = b"postgres-test-fingerprint-key-material-32-bytes!"
    fingerprint_key_id = "pg-identity-k1"
    fingerprint_key_b64 = base64.urlsafe_b64encode(fingerprint_key).rstrip(b"=").decode("ascii")
    monkeypatch.setenv("OLA_APPROVAL_IDENTITY_FINGERPRINT_KEY_B64", fingerprint_key_b64)
    monkeypatch.setenv("OLA_APPROVAL_IDENTITY_FINGERPRINT_KEY_ID", fingerprint_key_id)
    monkeypatch.setenv("OLA_APPROVAL_POLICY_VERSION", "human-gate-v1")
    monkeypatch.setenv("OLA_APPROVAL_POLICY_SHA256", "c" * 64)
    monkeypatch.setenv("OLA_APPROVAL_REQUIRED_ACR", "urn:example:loa:2")
    monkeypatch.setenv("OLA_APPROVAL_REQUIRED_AMR", "webauthn,mfa")

    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    signer_key_id = "pg-approval-k1"
    public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode("ascii")
    monkeypatch.setenv(
        "OLA_APPROVAL_ED25519_TRUSTED_KEYS_JSON",
        json.dumps({signer_key_id: public_b64}),
    )

    reviewer_fp = oidc_subject_fingerprint(
        fingerprint_key, fingerprint_key_id, ctx["tenant_id"], issuer, reviewer_subject,
    )["value"]
    requester_fp = oidc_subject_fingerprint(
        fingerprint_key, fingerprint_key_id, ctx["tenant_id"], issuer, requester_subject,
    )["value"]

    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO human_gate_memberships
                (id, tenant_id, issuer, subject_fingerprint, fingerprint_key_id,
                 role, membership_version, active, revoked_at, created_at)
            VALUES (%s, %s, %s, %s, %s, 'requester', 1, TRUE, NULL, %s)
            """,
            (ctx["requester_id"], ctx["tenant_id"], issuer, requester_fp,
             fingerprint_key_id, int(time.time())),
        )
        conn.exec_driver_sql(
            """
            INSERT INTO human_gate_memberships
                (id, tenant_id, issuer, subject_fingerprint, fingerprint_key_id,
                 role, membership_version, active, revoked_at, created_at)
            VALUES (%s, %s, %s, %s, %s, 'execution_approver', 1, TRUE, NULL, %s)
            """,
            (ctx["approver_id"], ctx["tenant_id"], issuer, reviewer_fp,
             fingerprint_key_id, int(time.time())),
        )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    auth_time = int(now.timestamp()) - 15
    session_id = "oidc-session-pg-intake-001"
    verified = approval_identity.VerifiedSubject(
        issuer=issuer,
        subject=reviewer_subject,
        tenant_id=ctx["tenant_id"],
        auth_time=auth_time,
        acr="urn:example:loa:2",
        amr=("webauthn", "mfa"),
        session_id=session_id,
    )
    monkeypatch.setattr(approval_identity, "verify_subject_token", lambda token: verified)

    client = TestClient(main.app)
    reason = "Independent approver reviewed the exact paid order and task digest."
    challenge_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval/challenge",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"reason": reason},
    )
    assert challenge_response.status_code == 200, challenge_response.text
    challenge = challenge_response.json()
    assert challenge["status"] == "CHALLENGE_READY"
    assert challenge["requires_external_signature"] is True
    assert challenge["private_key_available_in_ola"] is False
    assert signer_key_id in challenge["signing"]["key_ids"]
    payload = challenge["payload"]
    assert payload["evidence"]["tip_hash"] == post_payment_tip["record_hash"]
    assert payload["evidence"]["records"][-1]["id"] == post_payment_tip["id"]
    assert payload["evidence"]["records"][-1]["record_type"] == "integration.post_payment_audit_marker"
    signing_bytes = base64.urlsafe_b64decode(
        challenge["signing"]["input"]
        + "=" * ((4 - len(challenge["signing"]["input"]) % 4) % 4)
    )
    assert signing_bytes == signing_input(payload)
    assert hashlib.sha256(signing_bytes).hexdigest() == challenge["signing"]["input_sha256"]
    operation_id = payload["operation_id"]

    # A challenge is read-only: it does not create an approval, job or consume nonce.
    with database.SessionLocal() as db:
        challenge_control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == ctx["order_id"]
        ))
        assert challenge_control.status == "PAID_PENDING_REVIEW"
        assert challenge_control.approver_id is None
        assert challenge_control.signed_approval_envelope_json is None
        assert db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        )) is None
        assert db.scalars(select(HumanGateApprovalNonce).where(
            HumanGateApprovalNonce.tenant_id == ctx["tenant_id"]
        )).all() == []
        assert db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"],
            EvidenceRecord.record_type == "human.revenue_execution_approval",
        )).all() == []

    signature = base64.urlsafe_b64encode(
        private_key.sign(signing_bytes)
    ).rstrip(b"=").decode("ascii")
    envelope = {
        "payload": payload,
        "signature": {"algorithm": "Ed25519", "key_id": signer_key_id, "value": signature},
    }
    envelope_digest = signed_envelope_sha256(envelope)

    # Altered signature must fail before touching the order.
    invalid_signature = {
        "payload": envelope["payload"],
        "signature": {
            **envelope["signature"],
            "value": "A" * 86,
        },
    }
    invalid_signature_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": invalid_signature},
    )
    assert invalid_signature_response.status_code == 401, invalid_signature_response.text

    # A currently revoked or re-roled reviewer membership cannot submit.
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE human_gate_memberships SET role = 'report_reviewer' WHERE id = %s",
            (ctx["approver_id"],),
        )
    wrong_role_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert wrong_role_response.status_code == 403, wrong_role_response.text
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE human_gate_memberships SET role = 'execution_approver', membership_version = 2 WHERE id = %s",
            (ctx["approver_id"],),
        )
    changed_version_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert changed_version_response.status_code == 403, changed_version_response.text
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE human_gate_memberships SET membership_version = 1, active = FALSE, revoked_at = %s WHERE id = %s",
            (int(time.time()), ctx["approver_id"]),
        )
    revoked_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert revoked_response.status_code == 403, revoked_response.text
    with migration_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE human_gate_memberships SET active = TRUE, revoked_at = NULL WHERE id = %s",
            (ctx["approver_id"],),
        )

    # Same tenant and reviewer, but a different live OIDC sid must not bind.
    wrong_session = approval_identity.VerifiedSubject(
        issuer=issuer,
        subject=reviewer_subject,
        tenant_id=ctx["tenant_id"],
        auth_time=auth_time,
        acr=verified.acr,
        amr=verified.amr,
        session_id="different-oidc-session",
    )
    monkeypatch.setattr(approval_identity, "verify_subject_token", lambda token: wrong_session)
    wrong_session_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert wrong_session_response.status_code == 403, wrong_session_response.text

    # Stale step-up auth_time is independently rejected before any DB write.
    stale_session = approval_identity.VerifiedSubject(
        issuer=issuer,
        subject=reviewer_subject,
        tenant_id=ctx["tenant_id"],
        auth_time=auth_time - 600,
        acr=verified.acr,
        amr=verified.amr,
        session_id=session_id,
    )
    monkeypatch.setattr(approval_identity, "verify_subject_token", lambda token: stale_session)
    stale_response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert stale_response.status_code == 401, stale_response.text

    with database.SessionLocal() as db:
        unchanged_control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == ctx["order_id"]
        ))
        assert unchanged_control.status == "PAID_PENDING_REVIEW"
        assert unchanged_control.approver_id is None
        assert db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        )) is None

    monkeypatch.setattr(approval_identity, "verify_subject_token", lambda token: verified)
    response = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "APPROVED_FOR_EXECUTION"
    assert result["execution_job_id"] == operation_id
    assert result["execution_job_status"] == "QUEUED"
    assert result["production_authorized"] is False
    assert result["deployment_authorized"] is False

    with database.SessionLocal() as db:
        control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == ctx["order_id"]
        ))
        job = db.get(CheckoutExecutionJob, operation_id)
        approvals = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"],
            EvidenceRecord.record_type == "human.revenue_execution_approval",
        )).all()
        nonces = db.scalars(select(HumanGateApprovalNonce).where(
            HumanGateApprovalNonce.tenant_id == ctx["tenant_id"]
        )).all()
        event_payload = json.loads(approvals[0].payload_json)

    assert control.status == "APPROVED_FOR_EXECUTION"
    assert control.approver_id == ctx["approver_id"]
    assert json.loads(control.signed_approval_envelope_json) == envelope
    assert job is not None and job.status == "QUEUED" and job.attempt_count == 0
    assert job.approval_record_hash == approvals[0].record_hash
    assert approvals[0].prev_hash == post_payment_tip["record_hash"]
    assert event_payload["signed_approval_envelope_sha256"] == envelope_digest
    assert event_payload["approval_id"] == payload["approval_id"]
    assert nonces == []  # Human nonce is consumed only at the worker effect boundary.

    duplicate = client.post(
        f"/checkout-orders/{ctx['order_id']}/signed-approval",
        headers={"Authorization": "Bearer verified-oidc-token"},
        json={"envelope": envelope},
    )
    assert duplicate.status_code == 409, duplicate.text
    with database.SessionLocal() as db:
        assert db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        )).id == operation_id
        assert len(db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"],
            EvidenceRecord.record_type == "human.revenue_execution_approval",
        )).all()) == 1

    # Exercise the real PostgreSQL worker path. The external executor opens a
    # second session and must already observe RUNNING and the committed nonce.
    from app.paid_order_execution import execute_paid_order_job

    executor_calls = []

    def observe_committed_claim(tenant_arg, requester_arg, task_arg, tools_arg, *, execution_context=None):
        assert tenant_arg == ctx["tenant_id"]
        assert requester_arg == ctx["requester_id"]
        assert task_arg == ctx["task"]
        assert tools_arg == ["safe_expression"]
        assert execution_context == {
            "order_id": ctx["order_id"],
            "execution_job_id": operation_id,
        }
        with database.SessionLocal() as observer:
            persisted_job = observer.get(CheckoutExecutionJob, operation_id)
            nonce_rows = observer.scalars(select(HumanGateApprovalNonce).where(
                HumanGateApprovalNonce.tenant_id == ctx["tenant_id"],
                HumanGateApprovalNonce.approval_id == payload["approval_id"],
                HumanGateApprovalNonce.nonce == payload["nonce"],
            )).all()
            assert persisted_job is not None
            assert persisted_job.status == "RUNNING"
            assert persisted_job.attempt_count == 1
            assert len(nonce_rows) == 1
            assert nonce_rows[0].operation_id == operation_id
            assert nonce_rows[0].envelope_sha256 == envelope_digest
        executor_calls.append(execution_context)
        return {
            "nina": {"status": "BLOCK"},
            "igor": {"status": "BLOCK"},
            "provenance": {"status": "BLOCK"},
            "replay_verification": {"status": "BLOCK"},
            "decision_report": {},
        }

    result = execute_paid_order_job(operation_id, runner=observe_committed_claim)
    assert result["status"] == "EXECUTED_BLOCKED"
    assert len(executor_calls) == 1

    # A retry returns the durable result and cannot re-enter the executor.
    def forbidden_retry(*args, **kwargs):
        raise AssertionError("completed worker claim must not execute again")

    replay = execute_paid_order_job(operation_id, runner=forbidden_retry)
    assert replay["status"] == "EXECUTED_BLOCKED"
    with database.SessionLocal() as db:
        final_job = db.get(CheckoutExecutionJob, operation_id)
        final_nonces = db.scalars(select(HumanGateApprovalNonce).where(
            HumanGateApprovalNonce.tenant_id == ctx["tenant_id"],
            HumanGateApprovalNonce.approval_id == payload["approval_id"],
        )).all()
    assert final_job is not None
    assert final_job.status == "EXECUTED_BLOCKED"
    assert final_job.attempt_count == 1
    assert len(final_nonces) == 1
