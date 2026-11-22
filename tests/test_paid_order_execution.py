import pytest
from app.main import app



def _approve_signed(ctx, monkeypatch, *, reason="Reviewed payment and order scope"):
    """Build a test-only Signed Approval v1 record directly at the trusted test boundary."""
    import base64
    import json
    import uuid
    from datetime import datetime, timedelta, timezone

    import httpx
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from sqlalchemy import select

    from app.approval_contract_v1 import (
        oidc_subject_fingerprint, signing_input, validate_approval_semantics,
    )
    from app.database import SessionLocal, begin_write_transaction
    from app.evidence_writer import append_evidence_v4_locked
    from app.models import (
        ApiKey, CheckoutExecutionJob, CheckoutOrder, CheckoutOrderControl,
        EvidenceRecord, HumanGateMembership,
    )
    from app.runtime_provenance import runtime_source_commit
    from app.signed_approval_runtime import signed_envelope_sha256

    issuer = "https://login.example.test/tenant"
    fingerprint_key = b"ola-test-only-fingerprint-key-material-32-bytes!"
    fingerprint_key_id = "ci-identity-k1"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "ci-human-approval-k1"
    public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode("ascii")
    monkeypatch.setenv(
        "OLA_APPROVAL_ED25519_TRUSTED_KEYS_JSON",
        json.dumps({key_id: public_b64}),
    )
    monkeypatch.setenv("OLA_APPROVAL_POLICY_VERSION", "human-gate-v1")
    monkeypatch.setenv("OLA_APPROVAL_POLICY_SHA256", "c" * 64)
    monkeypatch.setenv("OLA_APPROVAL_REQUIRED_ACR", "urn:example:loa:2")
    monkeypatch.setenv("OLA_APPROVAL_REQUIRED_AMR", "webauthn,mfa")

    with SessionLocal() as db:
        order = db.get(CheckoutOrder, ctx["order_id"])
        control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == ctx["order_id"]
        ))
        if order is None or control is None or order.tenant_id != ctx["tenant_id"]:
            raise AssertionError("test paid-order fixture is incomplete")

        requester_fp = oidc_subject_fingerprint(
            fingerprint_key, fingerprint_key_id, ctx["tenant_id"],
            issuer, f"requester:{ctx['requester_id']}",
        )["value"]
        approver_fp = oidc_subject_fingerprint(
            fingerprint_key, fingerprint_key_id, ctx["tenant_id"],
            issuer, f"approver:{ctx['approver_id']}",
        )["value"]
        db.add_all([
            HumanGateMembership(
                id=ctx["requester_id"], tenant_id=ctx["tenant_id"], issuer=issuer,
                subject_fingerprint=requester_fp, fingerprint_key_id=fingerprint_key_id,
                role="requester", membership_version=1, active=True, revoked_at=None,
            ),
            HumanGateMembership(
                id=ctx["approver_id"], tenant_id=ctx["tenant_id"], issuer=issuer,
                subject_fingerprint=approver_fp, fingerprint_key_id=fingerprint_key_id,
                role="execution_approver", membership_version=1, active=True, revoked_at=None,
            ),
        ])
        db.commit()

        # Read the two trusted pre-approval records, then end the read transaction
        # before taking the tenant evidence-chain write lock.
        order = db.get(CheckoutOrder, ctx["order_id"])
        control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == ctx["order_id"]
        ))
        evidence_rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"]
        ).order_by(EvidenceRecord.seq.asc())).all()
        checkout = next(row for row in evidence_rows if row.record_type == "stripe.checkout_created")
        payment = next(row for row in evidence_rows if row.record_type == "stripe.payment_confirmed")
        if control.payment_evidence_id != payment.id or payment.record_hash != ctx["tip_hash"]:
            raise AssertionError("test signed approval must bind the current payment evidence tip")
        db.commit()

        job_id = str(uuid.uuid4())
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

        issued_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        auth_time = (now - timedelta(seconds=10)).isoformat(timespec="seconds").replace("+00:00", "Z")
        payload = {
            "schema": "ola.signed-approval/v1",
            "approval_id": str(uuid.uuid4()),
            "tenant_id": ctx["tenant_id"],
            "operation_id": job_id,
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
            "reviewer": actor(ctx["approver_id"], "execution_approver", approver_fp),
            "prior_approvers": [],
            "reviewer_authentication": {
                "auth_time": auth_time,
                "acr": "urn:example:loa:2",
                "amr": ["webauthn", "mfa"],
                "session_fingerprint": "d" * 64,
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
            "reason": reason,
            "nonce": str(uuid.uuid4()),
            "issued_at": issued_at,
            "expires_at": (now + timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "closure": {"operational": "OPEN", "epistemic": "OPEN", "remedial": "OPEN"},
        }
        validate_approval_semantics(payload, now=now)
        signature = base64.urlsafe_b64encode(
            private_key.sign(signing_input(payload))
        ).rstrip(b"=").decode("ascii")
        envelope = {
            "payload": payload,
            "signature": {"algorithm": "Ed25519", "key_id": key_id, "value": signature},
        }
        envelope_json = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        envelope_digest = signed_envelope_sha256(envelope)

        begin_write_transaction(db, tenant_id=ctx["tenant_id"])
        order = db.scalar(select(CheckoutOrder).where(
            CheckoutOrder.id == ctx["order_id"]
        ).with_for_update())
        control = db.scalar(select(CheckoutOrderControl).where(
            CheckoutOrderControl.order_id == ctx["order_id"]
        ).with_for_update())
        approval_record = append_evidence_v4_locked(
            db, ctx["tenant_id"], "human.revenue_execution_approval", {
                "event": "human.revenue_execution_approval",
                "order_id": order.id,
                "tenant_id": ctx["tenant_id"],
                "requester_id": ctx["requester_id"],
                "approver_id": ctx["approver_id"],
                "approver_role": "execution_approver",
                "reason": reason,
                "checkout_session_id": order.stripe_session_id,
                "stripe_event_id": order.payment_event_id,
                "checkout_evidence_id": checkout.id,
                "checkout_evidence_hash": checkout.record_hash,
                "payment_evidence_id": payment.id,
                "payment_evidence_hash": payment.record_hash,
                "request_hash": order.request_hash,
                "approved_tip_hash": payment.record_hash,
                "source_commit": runtime_source_commit(),
                "approved_at": int(now.timestamp()),
                "decision": "APPROVED_FOR_EXECUTION",
                "execution_authorized": True,
                "deployment_authorized": False,
                "production_authorized": False,
                "signed_approval_envelope_sha256": envelope_digest,
                "approval_id": payload["approval_id"],
                "operation_id": payload["operation_id"],
                "nonce": payload["nonce"],
            }, producer_id="ola_runtime",
        )
        control.status = "APPROVED_FOR_EXECUTION"
        control.approver_id = ctx["approver_id"]
        control.approval_reason = reason
        control.approved_tip_hash = payment.record_hash
        control.approval_record_hash = approval_record["record_hash"]
        control.approved_at = int(now.timestamp())
        control.signed_approval_envelope_json = envelope_json
        db.add(CheckoutExecutionJob(
            id=job_id,
            tenant_id=ctx["tenant_id"],
            order_id=order.id,
            approval_record_hash=approval_record["record_hash"],
            task=order.task,
            status="QUEUED",
            attempt_count=0,
        ))
        db.commit()

    return httpx.Response(200, json={
        "status": "APPROVED_FOR_EXECUTION",
        "order_id": ctx["order_id"],
        "execution": "QUEUED",
    })

@pytest.fixture(autouse=True)
def _sqlite_worker_nonce_adapter(monkeypatch, request):
    """Unit tests stub the PostgreSQL insert; one explicit test checks SQLite fail-closed."""
    if request.node.name == "test_worker_fails_closed_when_sqlite_nonce_ledger_is_unavailable":
        return
    from app.approval_nonce_ledger import PostgresApprovalNonceLedger
    monkeypatch.setattr(
        PostgresApprovalNonceLedger, "consume",
        lambda self, db, **kwargs: "test-only-postgres-nonce-consumed",
    )


def test_internal_paid_order_execution_worker_route_is_registered():
    routes = {route.path for route in app.routes}
    assert "/internal/checkout-execution/{job_id}/run" in routes


def test_worker_runs_paid_order_once_and_replays_completed_response(monkeypatch):
    import json
    from sqlalchemy import select
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob, EvidenceRecord
    from app.paid_order_execution import _append_locked
    from test_paid_order_approval import _seed_paid_order, _approve

    ctx = _seed_paid_order(monkeypatch)
    approved = _approve_signed(ctx, monkeypatch)
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        job_id = job.id
    token = "worker-secret-" + "w" * 40
    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", token)
    calls = []
    def fake_runner(tenant_id, requester_id, task, requested_tools, *, execution_context=None):
        calls.append((tenant_id, requester_id, task, requested_tools, execution_context))
        return {
            "run_id": "run-verified-001",
            "nina": {"status": "VERIFIED"},
            "igor": {"status": "VERIFIED"},
            "provenance": {"status": "VERIFIED"},
            "replay_verification": {"status": "VERIFIED"},
            "decision_report": {"report_sha256": "d" * 64},
            "status": "REVIEW",
        }
    import app.nina_execution as nina_execution
    # Patch the production runner behind the internal worker's explicit service boundary.
    monkeypatch.setattr(nina_execution, "run_nina_task", fake_runner)
    response = TestClient(app).post(
        f"/internal/checkout-execution/{job_id}/run",
        headers={"X-OLA-Worker-Token": token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "EXECUTED_REVIEW_REQUIRED"
    assert response.json()["customer_delivery"] == "NOT_DELIVERED"
    assert len(calls) == 1
    second = TestClient(app).post(
        f"/internal/checkout-execution/{job_id}/run",
        headers={"X-OLA-Worker-Token": token},
    )
    assert second.status_code == 200, second.text
    assert second.json() == response.json()
    assert len(calls) == 1
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        assert job.status == "EXECUTED_REVIEW_REQUIRED"
        assert job.attempt_count == 1
        records = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"]
        )).all()
        events = [row.record_type for row in records]
        assert events.count("revenue.execution_started") == 1
        assert events.count("revenue.execution_completed") == 1
        from app.igor_evidence_verifier import trusted_record
        worker_events = [row for row in records if row.record_type in {
            "revenue.execution_started", "revenue.execution_completed"
        }]
        assert len(worker_events) == 2
        assert all(trusted_record({
            "record_type": row.record_type,
            "payload_json": row.payload_json,
        }) for row in worker_events)


def test_worker_rejects_missing_or_wrong_token(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    token = "worker-secret-" + "w" * 40
    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", token)
    client = TestClient(app)
    missing = client.post("/internal/checkout-execution/not-a-job/run")
    wrong = client.post("/internal/checkout-execution/not-a-job/run", headers={"X-OLA-Worker-Token": "wrong"})
    assert missing.status_code == 401
    assert wrong.status_code == 403


def test_stale_running_job_is_marked_interrupted_and_never_replayed(monkeypatch):
    import time
    from sqlalchemy import select
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob, EvidenceRecord
    from test_paid_order_approval import _seed_paid_order, _approve
    ctx = _seed_paid_order(monkeypatch)
    assert _approve(ctx).status_code == 200
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        job.status = "RUNNING"
        job.attempt_count = 1
        job.started_at = int(time.time()) - 901
        db.commit()
        job_id = job.id
    token = "worker-secret-" + "w" * 40
    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", token)
    response = TestClient(app).post(
        f"/internal/checkout-execution/{job_id}/run",
        headers={"X-OLA-Worker-Token": token},
    )
    assert response.status_code == 409
    assert "manual reconciliation" in response.text
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        assert job.status == "INTERRUPTED"
        records = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"]
        )).all()
        assert sum(row.record_type == "revenue.execution_interrupted" for row in records) == 1


def test_nina_failure_is_terminal_and_does_not_auto_retry(monkeypatch):
    from sqlalchemy import select
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob, EvidenceRecord
    from test_paid_order_approval import _seed_paid_order, _approve
    import app.nina_execution as nina_execution
    ctx = _seed_paid_order(monkeypatch)
    assert _approve_signed(ctx, monkeypatch).status_code == 200
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        job_id = job.id
    token = "worker-secret-" + "w" * 40
    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", token)
    calls = []
    def failing_runner(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(nina_execution, "run_nina_task", failing_runner)
    client = TestClient(app)
    first = client.post(f"/internal/checkout-execution/{job_id}/run", headers={"X-OLA-Worker-Token": token})
    second = client.post(f"/internal/checkout-execution/{job_id}/run", headers={"X-OLA-Worker-Token": token})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "FAILED"
    assert second.status_code == 409
    assert len(calls) == 1
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        assert job.status == "FAILED"
        assert job.attempt_count == 1
        records = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == ctx["tenant_id"]
        )).all()
        assert sum(row.record_type == "revenue.execution_failed" for row in records) == 1


def test_worker_fails_closed_when_secret_is_not_configured(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv("OLA_EXECUTION_WORKER_TOKEN", raising=False)
    response = TestClient(app).post("/internal/checkout-execution/not-a-job/run")
    assert response.status_code == 503


def test_paid_order_worker_executes_real_nina_and_igor_runtime(monkeypatch):
    import json
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob, CheckoutOrder, EvidenceRecord
    from app.paid_order_execution import execute_paid_order_job
    from test_paid_order_approval import _seed_paid_order, _approve

    monkeypatch.setenv("OLA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _seed_paid_order(monkeypatch)
    approved = _approve_signed(ctx, monkeypatch)
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        job_id = job.id
    result = execute_paid_order_job(job_id)
    assert result["status"] == "EXECUTED_REVIEW_REQUIRED", result
    assert result["nina_status"] == "VERIFIED", result
    assert result["igor_status"] == "VERIFIED", result
    assert result["provenance_status"] == "VERIFIED", result
    assert result["replay_status"] == "VERIFIED", result
    assert result["customer_delivery"] == "NOT_DELIVERED"
    assert result["invocation_type"] == "local_deterministic_model"
    assert result["real_llm_invoked"] is False
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        order = db.get(CheckoutOrder, ctx["order_id"])
        assert job.status == "EXECUTED_REVIEW_REQUIRED"
        assert job.attempt_count == 1
        assert job.run_id == result["run_id"]
        assert order.status == "EXECUTED_REVIEW_REQUIRED"
        evidence = db.scalars(select(EvidenceRecord).where(EvidenceRecord.tenant_id == ctx["tenant_id"])).all()
        context_records = [row for row in evidence if row.record_type in {"provenance.runtime", "decision.candidate"}]
        assert any(json.loads(row.payload_json).get("order_id") == ctx["order_id"] for row in context_records)
        assert any(json.loads(row.payload_json).get("execution_job_id") == job_id for row in context_records)


def test_worker_blocks_changed_task_scope_before_running_nina(monkeypatch):
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob, CheckoutOrder
    from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected
    from test_paid_order_approval import _seed_paid_order, _approve
    ctx = _seed_paid_order(monkeypatch)
    assert _approve_signed(ctx, monkeypatch).status_code == 200
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        job_id = job.id
        job.task = "changed after approval"
        db.commit()
    with pytest.raises(PaidOrderExecutionRejected) as exc:
        execute_paid_order_job(job_id)
    assert exc.value.code == 409
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        order = db.get(CheckoutOrder, ctx["order_id"])
        assert job.status == "BLOCKED"
        assert job.attempt_count == 0
        assert order.status == "BLOCKED"


def test_worker_polling_selects_queued_and_stale_but_not_terminal_jobs(monkeypatch):
    import time
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob
    from scripts.run_paid_order_worker import pending_job_ids
    from test_paid_order_approval import _seed_paid_order, _approve
    ctx = _seed_paid_order(monkeypatch)
    assert _approve(ctx).status_code == 200
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        queued_id = job.id
        job.status = "RUNNING"
        job.attempt_count = 1
        job.started_at = 100
        db.commit()
    assert queued_id in pending_job_ids(now=1000, stale_after_seconds=900)
    assert queued_id not in pending_job_ids(now=1000, stale_after_seconds=901)


def test_worker_batch_exit_code_signals_execution_failure(monkeypatch):
    import scripts.run_paid_order_worker as worker
    monkeypatch.setattr(worker, "pending_job_ids", lambda **kwargs: ["job-failed"])
    monkeypatch.setattr(worker, "execute_paid_order_job", lambda *args, **kwargs: {"status": "FAILED"})
    assert worker.run_once(now=1000) == 1


def test_worker_batch_exit_code_is_zero_for_empty_queue(monkeypatch):
    import scripts.run_paid_order_worker as worker
    monkeypatch.setattr(worker, "pending_job_ids", lambda **kwargs: [])
    assert worker.run_once(now=1000) == 0


def test_worker_once_mode_propagates_failed_batch_exit_code(monkeypatch):
    import sys
    import scripts.run_paid_order_worker as worker
    monkeypatch.setattr(sys, "argv", ["run_paid_order_worker.py", "--once"])
    monkeypatch.setattr(worker, "prepare_runtime_schema", lambda: None)
    monkeypatch.setattr(worker, "run_once", lambda **kwargs: 1)
    assert worker.main() == 1


def test_concurrent_worker_invocations_claim_one_execution_only(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob
    from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected
    from sqlalchemy import select
    from test_paid_order_approval import _seed_paid_order, _approve

    ctx = _seed_paid_order(monkeypatch)
    assert _approve_signed(ctx, monkeypatch).status_code == 200
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == ctx["order_id"]))
        job_id = job.id

    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocked_runner(tenant_id, requester_id, task, requested_tools, *, execution_context=None):
        calls.append(job_id)
        started.set()
        assert release.wait(timeout=5), "test runner was not released"
        return {
            "run_id": "run-concurrent-001",
            "nina": {"status": "VERIFIED"},
            "igor": {"status": "VERIFIED"},
            "provenance": {"status": "VERIFIED"},
            "replay_verification": {"status": "VERIFIED"},
            "decision_report": {"report_sha256": "e" * 64},
            "status": "REVIEW",
        }

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(execute_paid_order_job, job_id, runner=blocked_runner)
        assert started.wait(timeout=5), "first worker did not claim the job"
        with pytest.raises(PaidOrderExecutionRejected) as exc:
            execute_paid_order_job(job_id, runner=blocked_runner)
        assert exc.value.code == 409
        assert "already running" in str(exc.value)
        release.set()
        result = first.result(timeout=10)

    assert result["status"] == "EXECUTED_REVIEW_REQUIRED"
    assert len(calls) == 1


def test_worker_rechecks_execution_approver_role_before_running_nina(monkeypatch):
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import ApiKey, CheckoutExecutionJob, CheckoutOrder
    from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected
    from test_paid_order_approval import _seed_paid_order, _approve

    ctx = _seed_paid_order(monkeypatch)
    approved = _approve_signed(ctx, monkeypatch)
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        approver = db.get(ApiKey, ctx["approver_id"])
        approver.role = "tenant"
        job = db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        ))
        job_id = job.id
        db.commit()

    calls = []
    def forbidden_runner(*args, **kwargs):
        calls.append(True)
        return {"status": "SHOULD_NOT_RUN"}

    with pytest.raises(PaidOrderExecutionRejected) as exc:
        execute_paid_order_job(job_id, runner=forbidden_runner)
    assert exc.value.code == 409
    assert calls == []
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        order = db.get(CheckoutOrder, ctx["order_id"])
    assert job.status == "BLOCKED"
    assert order.status == "BLOCKED"



def test_worker_refuses_legacy_unsigned_approval_before_runner(monkeypatch):
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob
    from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected
    from test_paid_order_approval import _seed_paid_order, _approve

    ctx = _seed_paid_order(monkeypatch)
    approved = _approve(ctx)
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        ))
        job_id = job.id

    calls = []
    def forbidden_runner(*args, **kwargs):
        calls.append(True)
        return {"status": "MUST_NOT_RUN"}

    with pytest.raises(PaidOrderExecutionRejected) as exc:
        execute_paid_order_job(job_id, runner=forbidden_runner)
    assert exc.value.code in {409, 503}
    assert calls == []
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        assert job.status == "BLOCKED"
        assert job.attempt_count == 0



def test_worker_fails_closed_when_sqlite_nonce_ledger_is_unavailable(monkeypatch):
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CheckoutExecutionJob
    from app.paid_order_execution import execute_paid_order_job, PaidOrderExecutionRejected
    from test_paid_order_approval import _seed_paid_order

    ctx = _seed_paid_order(monkeypatch)
    approved = _approve_signed(ctx, monkeypatch)
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        job = db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == ctx["order_id"]
        ))
        job_id = job.id

    calls = []
    def forbidden_runner(*args, **kwargs):
        calls.append(True)
        return {"status": "MUST_NOT_RUN"}

    with pytest.raises(PaidOrderExecutionRejected) as exc:
        execute_paid_order_job(job_id, runner=forbidden_runner)
    assert exc.value.code == 503
    assert calls == []
    with SessionLocal() as db:
        job = db.get(CheckoutExecutionJob, job_id)
        assert job.status == "QUEUED"
        assert job.attempt_count == 0
