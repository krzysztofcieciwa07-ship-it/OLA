"""Arithmetic failures must leave a blocked run, not a verified pseudo-result."""
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent_runtime import _safe_expression, run_agent_task
from app.api_key_crypto import hash_api_key
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant


TOOLS = ("safe_expression", "local_mcp_tool_registry.sha256")
INVALID_TASKS = (
    "Calculate 1 / 0",
    "Calculate 1e309",
    "Calculate 1e309 / 1e309",
    "Calculate 1e308 * 1e308",
    "Calculate 1 / (1e308 * 1e308)",
    "Calculate 1 / 1e309",
    "Calculate 1 +",
    "Calculate",
    'Calculate __import__("os")',
    "Calculate 2 ** 3",
    "1 / 0",
)


@pytest.fixture(autouse=True)
def deterministic_without_network(monkeypatch):
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.setenv("OLA_LLM_PROVIDER", "local")

    def forbidden_provider_call(*args, **kwargs):
        pytest.fail("arithmetic regression tests must not contact a provider")

    monkeypatch.setattr(httpx, "post", forbidden_provider_call)


def seed_tenant():
    tenant_id = str(uuid.uuid4())
    key = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="arithmetic-failure-test"))
        db.commit()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=hash_api_key(key)))
        db.commit()
    return tenant_id, key


def assert_persisted_block(tenant_id, result):
    assert result["status"] == "BLOCK"
    assert result["final_result"] is None
    assert result["reason"] == "MODEL_OR_TOOL_UNAVAILABLE"
    assert result["execution"] == []
    assert result["evidence_count"] == 1
    with SessionLocal() as db:
        records = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id)).all()
        assert len(records) == 1
        record = records[0]
        assert result["evidence_ids"] == [record.id]
        assert record.record_type == "runtime.blocked"
        payload = json.loads(record.payload_json)
    assert payload["run_id"] == result["run_id"]
    assert payload["status"] == "BLOCK"
    assert payload["agent"] == "codeact"
    assert payload["completed_agents"] == 0
    assert payload["error_type"] == "ValueError"


@pytest.mark.parametrize("task", INVALID_TASKS)
def test_invalid_arithmetic_persists_block_without_running_later_agents(task):
    tenant_id, _ = seed_tenant()
    result = run_agent_task(tenant_id, task, allowed_tools=TOOLS)
    assert_persisted_block(tenant_id, result)


@pytest.mark.parametrize("task", INVALID_TASKS)
def test_invalid_arithmetic_api_returns_controlled_block(task):
    tenant_id, key = seed_tenant()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/agent-run", headers={"X-API-Key": key},
                           json={"task": task, "requested_tools": list(TOOLS)})
    assert response.status_code == 200
    assert_persisted_block(tenant_id, response.json())


def test_valid_arithmetic_still_returns_verified_result():
    tenant_id, key = seed_tenant()
    client = TestClient(app)
    response = client.post("/agent-run", headers={"X-API-Key": key}, json={
        "task": "Calculate 17 * 23 and return the verified result.",
        "requested_tools": list(TOOLS),
    })
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "VERIFIED"
    assert result["final_result"] == "391"
    assert result["evidence_count"] == 6


def test_large_integer_does_not_require_lossy_float_conversion():
    value = 10 ** 400
    assert _safe_expression(f"Calculate {value} + 1") == str(value + 1)


@pytest.mark.parametrize("task", (
    "verify an evidence-backed task",
    "status",
    "Return the calculated evidence",
    "Explain the recalculated report",
    "Calculated evidence status",
))
def test_general_text_tasks_keep_existing_acknowledgement(task):
    tenant_id, _ = seed_tenant()
    result = run_agent_task(tenant_id, task, allowed_tools=TOOLS)
    assert result["status"] == "VERIFIED"
    assert result["final_result"].startswith("task accepted:")
