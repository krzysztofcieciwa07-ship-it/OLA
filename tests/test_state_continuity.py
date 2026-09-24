import os
import uuid

from app import main  # ensures all runtime tables are created for isolated test execution

from app.database import SessionLocal
from app.models import Tenant
from app.state_continuity import persist_checkpoint, recover_latest_checkpoint, verify_run_state


def test_checkpoint_persists_path_hash_and_state_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_STATE_DIR", str(tmp_path))
    tenant_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="state-test"))
        db.commit()

    first = persist_checkpoint(
        tenant_id=tenant_id,
        run_id=run_id,
        stage="execution.started",
        status="RUNNING",
        artifact={"kind": "runtime"},
    )
    second = persist_checkpoint(
        tenant_id=tenant_id,
        run_id=run_id,
        stage="execution.completed",
        status="VERIFIED",
        artifact={"result": "391"},
    )

    assert first["sequence"] == 0
    assert second["sequence"] == 1
    assert second["previous_hash"] == first["state_hash"]
    assert os.path.isfile(second["artifact_path"])
    assert verify_run_state(tenant_id, run_id)["status"] == "STABLE"


def test_checkpoint_tamper_blocks_state_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_STATE_DIR", str(tmp_path))
    tenant_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="state-tamper-test"))
        db.commit()

    checkpoint = persist_checkpoint(
        tenant_id=tenant_id,
        run_id=run_id,
        stage="execution.completed",
        status="VERIFIED",
        artifact={"result": "391"},
    )
    with open(checkpoint["artifact_path"], "w", encoding="utf-8") as handle:
        handle.write('{"tampered":true}')

    result = verify_run_state(tenant_id, run_id)
    assert result["status"] == "BLOCK"
    assert "hash" in result["reason"]


def test_latest_checkpoint_is_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_STATE_DIR", str(tmp_path))
    tenant_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="state-recovery-test"))
        db.commit()

    persist_checkpoint(
        tenant_id=tenant_id,
        run_id=run_id,
        stage="execution.started",
        status="RUNNING",
        artifact={"step": 1},
    )
    persist_checkpoint(
        tenant_id=tenant_id,
        run_id=run_id,
        stage="execution.completed",
        status="VERIFIED",
        artifact={"step": 2, "result": "391"},
    )

    recovered = recover_latest_checkpoint(tenant_id, run_id)
    assert recovered["status"] == "RECOVERED"
    assert recovered["sequence"] == 1
    assert recovered["state"]["artifact"]["result"] == "391"
