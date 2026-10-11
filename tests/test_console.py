"""Real API contract for the UI; the six-agent runtime is not mocked."""
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, Tenant

ROOT = Path(__file__).resolve().parents[1]


def tenant_key():
    tenant = str(uuid.uuid4())
    key = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="console-test"))
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=hashlib.sha256(key.encode()).hexdigest()))
        db.commit()
    return tenant, key


@pytest.mark.parametrize("path", ["/", "/console/app.mjs", "/console/model.mjs", "/console/style.css"])
def test_console_assets_are_served_with_restricted_policy(path):
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_session_validates_tenant_and_never_echoes_key():
    client = TestClient(app)
    assert client.get("/console/session").status_code == 401
    assert client.get("/console/session", headers={"X-API-Key": "invalid"}).status_code == 401
    tenant, key = tenant_key()
    response = client.get("/console/session", headers={"X-API-Key": key})
    assert response.status_code == 200
    assert response.json() == {"tenant_id": tenant}
    assert key not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_console_real_runtime_evidence_and_cross_tenant_denial(monkeypatch):
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    monkeypatch.setenv("OLA_SOURCE_COMMIT", source)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", source)
    monkeypatch.setenv("OLA_LLM_PROVIDER", "local")
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tenant, key = tenant_key()
    _, foreign_key = tenant_key()
    client = TestClient(app)
    headers = {"X-API-Key": key}
    task = "calculate 17*23"
    response = client.post("/nina-run", headers=headers,
                           json={"task": task, "requested_tools": ["safe_expression"]})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["igor"]["status"] == "VERIFIED"
    assert data["replay_verification"]["status"] == "VERIFIED"
    assert data["status"] == "REVIEW"
    assert data["status_fields"]["HUMAN_GATE"] == "REVIEW"
    records = []
    for record_id in data["decision_report"]["evidence_ids"]:
        path = f"/evidence/{record_id}"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-API-Key": foreign_key}).status_code == 404
        record = client.get(path, headers=headers)
        assert record.status_code == 200
        records.append(record.json())
    assert len(records) == 7
    assert records[-2]["payload"].get("final_result") == "391"
    assert all(record["payload"]["run_id"] == data["run_id"] for record in records)
