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
            # Human Gate memberships are managed out-of-band; runtime is read-only.
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



def test_postgres_runtime_rejects_write_access_to_human_gate_memberships(postgres_db):
    database, runtime_engine, _migration_engine, admin_engine, runtime_role, schema = postgres_db

    # A runtime role that can grant itself or another caller an approval role
    # would defeat the out-of-band membership ownership boundary.
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



def test_signed_approval_ingress_binds_live_oidc_session_and_queues_once(postgres_db, monkeypatch):
    import base64
    import hashlib
    import json
    import time
    import uuid
    from datetime import datetime, timedelta, timezone

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import approval_identity, main, database
    from app.api_key_hashing import api_key_fingerprint
    from app.approval_contract_v1 import (
        oidc_session_fingerprint,
        oidc_subject_fingerprint,
        signing_input,
        validate_approval_semantics,
    )
    from app.models import (
        ApiKey, CheckoutExecutionJob, CheckoutOrder, CheckoutOrderControl,
        EvidenceRecord, HumanGateApprovalNonce, HumanGateMembership, Tenant,
    )
    from app.runtime_provenance import runtime_source_commit
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

    with database.SessionLocal() as db:
        order = db.get(CheckoutOrder, ctx["order_id"])
        evidence_rows = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == ctx["tenant_id"])
            .order_by(EvidenceRecord.seq.asc())
        ).all()
        checkout = next(row for row in evidence_rows if row.record_type == "stripe.checkout_created")
        payment = next(row for row in evidence_rows if row.record_type == "stripe.payment_confirmed")
        assert evidence_rows[-1].record_hash == payment.record_hash == ctx["tip_hash"]
        operation_id = str(uuid.uuid4())

    def actor(principal_id, role, fingerprint):
        return {
            "principal_id": principal_id,
            "tenant_id": ctx["tenant_id"],
            "issuer": issuer,
            "subject_fingerprint": fingerprint,
            "fingerprint_key_id": fingerprint_key_id,
            "role": role,
            "membership_version": 1,
        }

    auth_time_text = datetime.fromtimestamp(
        auth_time, tz=timezone.utc,
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {
        "schema": "ola.signed-approval/v1",
        "approval_id": str(uuid.uuid4()),
        "tenant_id": ctx["tenant_id"],
        "operation_id": operation_id,
        "request": {
            "action": "EXECUTE_PAID_ORDER",
            "resource_type": "checkout_order",
            "resource_id": order.id,
            "sha256": order.request_hash,
        },
        "effect": {
            "action": "QUEUE_SINGLE_EXECUTION",
            "target_id": order.id,
            "target_sha256": order.request_hash,
        },
        "decision": "ALLOW",
        "effect_authorized": True,
        "execution_observed": "NOT_STARTED",
        "author": actor(ctx["requester_id"], "requester", requester_fp),
        "reviewer": actor(ctx["approver_id"], "execution_approver", reviewer_fp),
        "prior_approvers": [],
        "reviewer_authentication": {
            "auth_time": auth_time_text,
            "acr": verified.acr,
            "amr": list(verified.amr),
            "session_fingerprint": oidc_session_fingerprint(
                fingerprint_key, fingerprint_key_id, ctx["tenant_id"],
                issuer, reviewer_subject, session_id,
            )["value"],
        },
        "policy": {"version": "human-gate-v1", "sha256": "c" * 64},
        "evidence": {
            "tip_hash": payment.record_hash,
            "records": [
                {
                    "id": checkout.id, "sequence": checkout.seq,
                    "record_type": checkout.record_type, "record_hash": checkout.record_hash,
                },
                {
                    "id": payment.id, "sequence": payment.seq,
                    "record_type": payment.record_type, "record_hash": payment.record_hash,
                },
            ],
        },
        "runtime": {"source_commit": runtime_source_commit()},
        "reason": "Independent approver reviewed the paid order and exact task digest.",
        "nonce": str(uuid.uuid4()),
        "issued_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "closure": {"operational": "OPEN", "epistemic": "OPEN", "remedial": "OPEN"},
    }
    validate_approval_semantics(payload, now=now)
    signature = base64.urlsafe_b64encode(
        private_key.sign(signing_input(payload))
    ).rstrip(b"=").decode("ascii")
    envelope = {
        "payload": payload,
        "signature": {"algorithm": "Ed25519", "key_id": signer_key_id, "value": signature},
    }
    envelope_digest = signed_envelope_sha256(envelope)

    client = TestClient(main.app)

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
    assert approvals[0].prev_hash == payment.record_hash
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
