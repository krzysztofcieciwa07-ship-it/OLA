import hashlib
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Tenant, ApiKey
import app.agent_runtime as agent_runtime


def _tenant(key):
    with SessionLocal() as db:
        tenant_id = str(uuid.uuid4())
        db.add(Tenant(id=tenant_id, name="parallel-workflow-test"))
        db.commit()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=hashlib.sha256(key.encode()).hexdigest()))
        db.commit()


def test_workflow_endpoint_is_disabled_by_default(monkeypatch):
    key = f"workflow-gate-{uuid.uuid4()}"
    _tenant(key)
    monkeypatch.delenv("OLA_PARALLEL_WORKFLOWS_ENABLED", raising=False)
    response = TestClient(app).post("/nina-workflow",
        headers={"X-API-Key": key}, json={"task": "analyse the goal"})
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_workflow_endpoint_runs_real_route_with_mocked_external_model(monkeypatch):
    key = f"workflow-enabled-{uuid.uuid4()}"
    _tenant(key)
    monkeypatch.setenv("OLA_PARALLEL_WORKFLOWS_ENABLED", "1")
    calls = []

    def fake_provider(agent, task, context):
        calls.append(agent)
        if agent == "nina_dag_planner":
            return {
                "invocation_type": "real_llm", "response_id": "plan-response-id",
                "provider": "ollama", "model": "mock-model",
                "output": '{"nodes":[{"id":"analyst","tool":"llm_agent","task":"analyse","needs":[]},'
                          '{"id":"reviewer","tool":"llm_agent","task":"review","needs":["analyst"]}]}',
            }
        return {
            "invocation_type": "real_llm", "response_id": f"agent-{agent}",
            "provider": "ollama", "model": "mock-model", "output": f"result:{agent}",
        }

    monkeypatch.setattr(agent_runtime, "_invoke_llm", fake_provider)
    response = TestClient(app).post("/nina-workflow",
        headers={"X-API-Key": key}, json={"task": "analyse, review and report"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED_UNVERIFIED"
    assert body["verified"] is False
    assert body["human_gate"] == "NOT_APPROVED"
    assert len(body["evidence_ids"]) == 6
    assert calls == ["nina_dag_planner", "analyst", "reviewer"]


def test_external_api_cannot_forge_dag_runtime_provenance():
    """Untrusted callers must never create trusted workflow/approval events."""
    from sqlalchemy import select
    from app.models import EvidenceRecord

    key = f"workflow-spoof-{uuid.uuid4()}"
    _tenant(key)
    client = TestClient(app)
    for record_type in (
        "workflow.planned", "task.started", "task.completed",
        "workflow.completed", "human.workflow_approval",
    ):
        result = client.post("/evidence", headers={"X-API-Key": key},
                             json={"record_type": record_type, "payload": {
                                 "event": record_type, "requester_id": "faked-other-user",
                             }})
        assert result.status_code == 403, (record_type, result.text)

    with SessionLocal() as db:
        assert db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.record_type.in_((
                    "workflow.planned", "task.started", "task.completed",
                    "workflow.completed", "human.workflow_approval",
                ))
            )
        ).first() is None


def test_external_api_still_accepts_unreserved_evidence():
    key = f"workflow-evidence-{uuid.uuid4()}"
    _tenant(key)
    result = TestClient(app).post(
        "/evidence", headers={"X-API-Key": key},
        json={"record_type": "customer.proof", "payload": {"kind": "customer"}},
    )
    assert result.status_code == 200, result.text
    assert result.json()["record_hash"]


def test_nina_parallel_gate_checks_out_exact_head_on_pr_and_runs_on_main_push():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]
              / ".github/workflows/nina-parallel-dag.yml").read_text()
    assert "\n  push:\n    branches: [main]\n" in source
    assert "\n  pull_request:\n    branches: [main]\n" in source
    assert "    paths:" not in source  # required gate cannot be skipped by path filters
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in source
    assert "git rev-parse HEAD" in source


def test_final_production_gate_attests_actual_checked_out_commit():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]
              / ".github/workflows/final-production-gate.yml").read_text()
    assert "ref: ${{ steps.target.outputs.sha }}" in source
    assert "git rev-parse HEAD" in source
