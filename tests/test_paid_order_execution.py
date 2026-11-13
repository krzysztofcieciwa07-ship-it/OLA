import pytest
from app.main import app


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
    approved = _approve(ctx)
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
        from app.hashchain import trusted_record
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
    assert _approve(ctx).status_code == 200
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
    approved = _approve(ctx)
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
    assert _approve(ctx).status_code == 200
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
    assert _approve(ctx).status_code == 200
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


def test_internal_worker_route_forwards_tenant_and_claim_token(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    worker_token = "worker-secret-" + "w" * 40
    tenant_id = "tenant-claim-123"
    claim_token = "claim-token-4567"
    job_id = "job-claim-789"
    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", worker_token)
    received = {}

    def fake_execute(job_id_arg, **kwargs):
        received["job_id"] = job_id_arg
        received.update(kwargs)
        return {"status": "CLAIM_ACCEPTED"}

    monkeypatch.setattr(main, "execute_paid_order_job", fake_execute)
    response = TestClient(main.app).post(
        f"/internal/checkout-execution/{job_id}/run",
        headers={
            "X-OLA-Worker-Token": worker_token,
            "X-OLA-Tenant-ID": tenant_id,
            "X-OLA-Claim-Token": claim_token,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "CLAIM_ACCEPTED"}
    assert received == {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "claim_token": claim_token,
    }


def test_postgres_worker_batch_claims_and_dispatches_only_claim_coordinates(monkeypatch):
    from types import SimpleNamespace
    import scripts.run_paid_order_worker as worker

    class FakeConnection:
        def execute(self, statement, params):
            assert "ola_claim_checkout_jobs" in str(statement)
            assert params == {"limit": 20, "stale_after": 900}
            return [
                SimpleNamespace(job_id="job-1", tenant_id="tenant-1", claim_token="claim-token-000000000001"),
            ]

    class FakeEngine:
        def begin(self):
            class Transaction:
                def __enter__(self):
                    return FakeConnection()

                def __exit__(self, exc_type, exc, traceback):
                    return False
            return Transaction()

    dispatched = []
    def fake_dispatch(api_url, worker_token, claim, *, stale_after_seconds=900):
        dispatched.append((api_url, worker_token, claim, stale_after_seconds))
        return {"status": "ACCEPTED"}

    monkeypatch.setattr(worker, "dispatch_claim_to_api", fake_dispatch)
    result = worker.run_once(
        worker_engine=FakeEngine(),
        api_url="https://ola-internal.example",
        worker_token="worker-secret-" + "w" * 40,
    )

    assert result == 0
    assert dispatched == [(
        "https://ola-internal.example",
        "worker-secret-" + "w" * 40,
        {"job_id": "job-1", "tenant_id": "tenant-1", "claim_token": "claim-token-000000000001"},
        900,
    )]


def test_postgres_worker_execution_fails_closed_without_claim_coordinates(monkeypatch):
    from types import SimpleNamespace
    import app.paid_order_execution as execution

    class ProbeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get_bind(self):
            return self.bind

    monkeypatch.setattr(execution, "SessionLocal", ProbeSession)
    with pytest.raises(execution.PaidOrderExecutionRejected) as exc:
        execution.execute_paid_order_job("job-without-claim")
    assert exc.value.code == 409
    assert "claim token" in str(exc.value)


def test_postgres_worker_http_dispatch_sends_claim_only_as_headers(monkeypatch):
    import scripts.run_paid_order_worker as worker

    seen = {}
    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, traceback):
            return False
        def read(self):
            return b'{"status":"ACCEPTED"}'

    class FakeOpener:
        def open(self, request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["headers"] = {key.lower(): value for key, value in request.header_items()}
            return FakeResponse()

    monkeypatch.setattr(worker, "build_opener", lambda handler: FakeOpener())
    result = worker.dispatch_claim_to_api(
        "https://ola-internal.example",
        "worker-secret-" + "w" * 40,
        {"job_id": "job-123", "tenant_id": "tenant-456", "claim_token": "claim-token-789-123456"},
    )
    assert result == {"status": "ACCEPTED"}
    assert seen["url"] == "https://ola-internal.example/internal/checkout-execution/job-123/run"
    assert "tenant-456" not in seen["url"]
    assert "claim-token-789-123456" not in seen["url"]
    assert seen["headers"]["x-ola-worker-token"] == "worker-secret-" + "w" * 40
    assert seen["headers"]["x-ola-tenant-id"] == "tenant-456"
    assert seen["headers"]["x-ola-claim-token"] == "claim-token-789-123456"
    assert seen["headers"]["x-ola-claim-stale-after"] == "900"
    assert seen["timeout"] == 20


def test_postgres_claim_validation_binds_tenant_token_and_expiry():
    from types import SimpleNamespace
    from app.paid_order_execution import _postgres_claim_is_current

    job = SimpleNamespace(tenant_id="tenant-1", claim_token="claim-token-123456", claimed_at=1_000)
    assert _postgres_claim_is_current(
        job, "tenant-1", "claim-token-123456", now=1_100, stale_after_seconds=900,
    ) is True
    assert _postgres_claim_is_current(
        job, "tenant-2", "claim-token-123456", now=1_100, stale_after_seconds=900,
    ) is False
    assert _postgres_claim_is_current(
        job, "tenant-1", "wrong-token-123456", now=1_100, stale_after_seconds=900,
    ) is False
    assert _postgres_claim_is_current(
        job, "tenant-1", "claim-token-123456", now=2_000, stale_after_seconds=900,
    ) is False
    assert _postgres_claim_is_current(
        job, "tenant-1", "claim-token-123456", now=900, stale_after_seconds=900,
    ) is False
    assert _postgres_claim_is_current(
        job, "tenant-1", "claim-token-12☃", now=1_100, stale_after_seconds=900,
    ) is False


def test_postgres_worker_refuses_shared_runtime_database_without_worker_dsn(monkeypatch):
    import sys
    from types import SimpleNamespace
    import scripts.run_paid_order_worker as worker

    monkeypatch.setattr(
        worker, "runtime_engine",
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.delenv("OLA_DATABASE_WORKER_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_paid_order_worker.py", "--once"])
    with pytest.raises(SystemExit, match="OLA_DATABASE_WORKER_URL"):
        worker.main()


def test_postgres_worker_route_accepts_claim_and_schedules_execution(monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    import app.main as main

    worker_token = "worker-secret-" + "w" * 40
    tenant_id = "tenant-claim-123"
    claim_token = "claim-token-4567"
    job_id = "job-claim-789"
    received = {}

    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", worker_token)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))

    def fake_validate(job_id_arg, tenant_id_arg, claim_token_arg, *, stale_after_seconds=900):
        received["validated"] = (job_id_arg, tenant_id_arg, claim_token_arg, stale_after_seconds)

    def fake_execute(job_id_arg, **kwargs):
        received["executed"] = (job_id_arg, kwargs)

    monkeypatch.setattr(main, "validate_postgres_worker_claim", fake_validate)
    monkeypatch.setattr(main, "execute_paid_order_job", fake_execute)
    response = TestClient(main.app).post(
        f"/internal/checkout-execution/{job_id}/run",
        headers={
            "X-OLA-Worker-Token": worker_token,
            "X-OLA-Tenant-ID": tenant_id,
            "X-OLA-Claim-Token": claim_token,
        },
    )

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "ACCEPTED", "job_id": job_id}
    assert received["validated"] == (job_id, tenant_id, claim_token, 900)
    assert received["executed"] == (
        job_id, {
            "tenant_id": tenant_id,
            "claim_token": claim_token,
            "stale_after_seconds": 900,
        },
    )


def test_worker_token_rejects_non_ascii_and_invalid_configuration(monkeypatch):
    from app.paid_order_execution import PaidOrderExecutionRejected, verify_worker_token

    valid_token = "worker-secret-" + "a" * 40
    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", valid_token)
    with pytest.raises(PaidOrderExecutionRejected) as incoming:
        verify_worker_token("worker-secret-☃" + "a" * 40)
    assert incoming.value.code == 401

    monkeypatch.setenv("OLA_EXECUTION_WORKER_TOKEN", "worker-secret-☃" + "a" * 40)
    with pytest.raises(PaidOrderExecutionRejected) as configured:
        verify_worker_token(valid_token)
    assert configured.value.code == 503


def test_postgres_worker_rejects_non_acceptance_response(monkeypatch):
    from types import SimpleNamespace
    import scripts.run_paid_order_worker as worker

    class FakeConnection:
        def execute(self, statement, params):
            return [
                SimpleNamespace(job_id="job-1", tenant_id="tenant-1", claim_token="claim-token-123456"),
            ]

    class FakeEngine:
        def begin(self):
            class Transaction:
                def __enter__(self):
                    return FakeConnection()
                def __exit__(self, exc_type, exc, traceback):
                    return False
            return Transaction()

    monkeypatch.setattr(
        worker, "dispatch_claim_to_api",
        lambda *args, **kwargs: {"status": "UNEXPECTED"},
    )
    assert worker.run_once(
        worker_engine=FakeEngine(),
        api_url="https://ola-internal.example",
        worker_token="worker-secret-" + "w" * 40,
    ) == 1


@pytest.mark.parametrize(
    ("limit", "stale_after_seconds"),
    [
        (0, 900),
        (101, 900),
        (20, 59),
        (20, 86401),
    ],
)
def test_postgres_worker_rejects_invalid_claim_bounds_before_db_access(limit, stale_after_seconds):
    import scripts.run_paid_order_worker as worker

    with pytest.raises(ValueError):
        worker.claim_postgres_jobs(
            None, limit=limit, stale_after_seconds=stale_after_seconds,
        )
