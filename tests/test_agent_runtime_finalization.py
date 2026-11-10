import json
import uuid

from sqlalchemy import select

from app.api_key_hashing import api_key_fingerprint
from app.agent_runtime import AGENT_ROLES, run_agent_task
from app.database import SessionLocal
from app.models import ApiKey, EvidenceRecord, Tenant


TEST_SOURCE_COMMIT = "d" * 40


def _tenant(api_key):
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="agent-finalization-test"))
        db.commit()
        db.add(ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(api_key),
        ))
        db.commit()
    return tenant_id


def _run_records(tenant_id, run_id):
    with SessionLocal() as db:
        rows = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.asc())
        ).all()
    selected = []
    for row in rows:
        payload = json.loads(row.payload_json)
        if payload.get("run_id") == run_id:
            selected.append((row.record_type, payload))
    return selected


def test_verifier_is_called_only_after_terminal_record_exists(monkeypatch):
    from app import agent_runtime

    monkeypatch.setenv("OLA_RUNTIME_COMMIT", TEST_SOURCE_COMMIT)
    tenant_id = _tenant("finalization-order-key")
    original = agent_runtime.verify_agent_run
    observed = []

    def verify_after_end(tenant, run_id):
        records = _run_records(tenant, run_id)
        observed.append([record_type for record_type, _ in records])
        assert "execution.run.end" in observed[-1], (
            "verifier must not run before the terminal lifecycle record is durable"
        )
        return original(tenant, run_id)

    monkeypatch.setattr(agent_runtime, "verify_agent_run", verify_after_end)
    result = run_agent_task(tenant_id, "verify finalization ordering")

    assert result["status"] == "VERIFIED"
    assert observed
    assert observed[0].index("execution.run.end") > observed[0].index("execution.run.start")


def test_terminal_append_failure_is_pending_and_can_be_retried_idempotently(monkeypatch):
    from app import agent_runtime

    monkeypatch.setenv("OLA_RUNTIME_COMMIT", TEST_SOURCE_COMMIT)
    tenant_id = _tenant("finalization-retry-key")
    original_append = agent_runtime.append_evidence_atomic
    failures = {"remaining": 1}

    def fail_first_terminal_append(tenant, record_type, payload, **kwargs):
        if record_type == "execution.run.end" and failures["remaining"]:
            failures["remaining"] -= 1
            raise OSError("synthetic terminal storage outage")
        return original_append(tenant, record_type, payload, **kwargs)

    monkeypatch.setattr(agent_runtime, "append_evidence_atomic", fail_first_terminal_append)
    result = run_agent_task(tenant_id, "recover terminal evidence")

    assert result["status"] == "FINALIZATION_PENDING"
    assert result["run_id"]
    assert result["evidence_count"] == len(AGENT_ROLES)
    assert "VERIFIED" not in result["status"]

    finalized = agent_runtime.finalize_agent_run(tenant_id, result["run_id"])
    assert finalized["status"] == "VERIFIED"

    # A second retry must not append a duplicate terminal record.
    again = agent_runtime.finalize_agent_run(tenant_id, result["run_id"])
    assert again["status"] == "VERIFIED"
    terminal = [
        payload for record_type, payload in _run_records(tenant_id, result["run_id"])
        if record_type == "execution.run.end"
    ]
    assert len(terminal) == 1
    assert terminal[0]["status"] == "COMPLETED"
    assert terminal[0]["completed_agent_count"] == len(AGENT_ROLES)
