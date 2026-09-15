import hashlib
import os
import tempfile
import uuid

os.environ["OLA_EG_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="ola_agent_runtime_"), "agent_runtime.db"
)

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models import ApiKey, EvidenceRecord, Tenant
from app.agent_runtime import AGENT_ROLES, run_agent_task, verify_agent_run


def _seed_tenant():
    db = SessionLocal()
    tenant = Tenant(id=str(uuid.uuid4()), name="agent-runtime-test")
    db.add(tenant)
    db.commit()
    db.add(ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        key_hash=hashlib.sha256(b"agent-key").hexdigest(),
    ))
    db.commit()
    db.close()
    return tenant.id


def test_six_agent_runtime_is_ordered_and_verified():
    tenant_id = _seed_tenant()
    result = run_agent_task(tenant_id, "verify an evidence-backed task")

    assert result["status"] == "VERIFIED"
    assert result["agents"] == AGENT_ROLES
    assert result["evidence_count"] == 6
    assert verify_agent_run(tenant_id, result["run_id"])["status"] == "VERIFIED"


def test_independent_verifier_rejects_missing_agent_evidence():
    tenant_id = _seed_tenant()
    result = run_agent_task(tenant_id, "task with complete evidence")

    db = SessionLocal()
    row = db.scalar(
        select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
            EvidenceRecord.id == result["evidence_ids"][-1],
        )
    )
    db.delete(row)
    db.commit()
    db.close()

    assert verify_agent_run(tenant_id, result["run_id"])["status"] in {"UNKNOWN", "BLOCK"}


def test_agent_runtime_http_endpoint():
    _seed_tenant()
    client = TestClient(app)
    response = client.post(
        "/agent-run",
        headers={"X-API-Key": "agent-key"},
        json={"task": "runtime agent verification"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"
