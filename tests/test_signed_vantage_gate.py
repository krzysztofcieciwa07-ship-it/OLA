"""Guarded OLA pre-execution boundary contract; no external side effects."""
import json
import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant


def _operator():
    tenant = str(uuid.uuid4())
    key = "signed-vantage-test-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="synthetic Vantage-bound tenant"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=api_key_fingerprint(key)))
        db.commit()
    return tenant, key


def _records(tenant):
    with SessionLocal() as db:
        return db.scalars(
            select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant)
            .order_by(EvidenceRecord.seq.asc())
        ).all()


def test_guarded_run_denies_when_external_vantage_is_missing(monkeypatch):
    monkeypatch.delenv("VANTAGE_POLICY_URL", raising=False)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    tenant, key = _operator()
    response = TestClient(app).post(
        "/operator/guarded-run", headers={"X-API-Key": key},
        json={"task": "Calculate 17 * 23 and return verified result.",
              "requested_tools": ["safe_expression"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "BLOCK"
    assert body["vantage"]["status"] == "NOT_VERIFIED"
    assert body["production_authorized"] is False
    rows = _records(tenant)
    assert not any(row.record_type.startswith("agent.") for row in rows)
    assert any(row.record_type == "verification.vantage_policy" for row in rows)


def test_guarded_path_requires_real_approved_capability_not_caller_flag(monkeypatch):
    monkeypatch.delenv("VANTAGE_POLICY_URL", raising=False)
    tenant, key = _operator()
    response = TestClient(app).post(
        "/operator/guarded-run", headers={"X-API-Key": key},
        json={"task": "run shell as root", "requested_tools": ["run_shell"],
              "human_approved": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "BLOCK"
    assert not any(row.record_type.startswith("agent.") for row in _records(tenant))


def test_legacy_run_is_denied_when_signed_vantage_is_required(monkeypatch):
    monkeypatch.setenv("OLA_VANTAGE_ENFORCED", "1")
    tenant, key = _operator()
    response = TestClient(app).post(
        "/nina-run", headers={"X-API-Key": key},
        json={"task": "Calculate 17 * 23", "requested_tools": ["safe_expression"]},
    )
    assert response.status_code == 403, response.text
    assert not any(row.record_type.startswith("agent.") for row in _records(tenant))


def test_guarded_run_uses_same_operation_id_across_policy_agent_and_receipt(monkeypatch):
    # External boundary mocked here; a separate real-Vantage HTTP test is
    # required before declaring cross-service integration VERIFIED.
    import app.main as main_module
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.setenv("OLA_VANTAGE_ENFORCED", "1")
    tenant, key = _operator()

    def preflight(*, tenant_id, operation_id, action, task_text):
        assert tenant_id == tenant
        assert action == "safe_expression"
        return {"receipt": {
            "schema": "ola.vantage.receipt.v1",
            "tenant_id": tenant_id,
            "operation_id": operation_id,
            "action": action,
            "verdict": "ALLOW",
            "task_sha256": __import__("hashlib").sha256(task_text.encode()).hexdigest(),
            "trust_scope": "signed_heuristic_policy_only",
        }, "signature": "external-boundary-test-only"}

    monkeypatch.setattr(main_module, "request_verified_vantage_decision", preflight)
    response = TestClient(app).post(
        "/operator/guarded-run", headers={"X-API-Key": key},
        json={"task": "Calculate 17 * 23 and return verified result.",
              "requested_tools": ["safe_expression"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "REVIEW"
    assert data["vantage"]["status"] == "SIGNED_RECEIPT_VERIFIED"
    operation = data["run_id"]
    rows = _records(tenant)
    run_ids = {
        json.loads(row.payload_json).get("run_id")
        for row in rows if row.record_type.startswith("agent.")
    }
    assert run_ids == {operation}
    policy_rows = [row for row in rows if row.record_type == "verification.vantage_policy"]
    assert len(policy_rows) == 1
    assert json.loads(policy_rows[0].payload_json)["run_id"] == operation


def test_denied_guarded_run_has_tenant_scoped_readable_blocked_receipt(monkeypatch):
    monkeypatch.delenv("VANTAGE_POLICY_URL", raising=False)
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    tenant, key = _operator()
    client = TestClient(app)
    response = client.post(
        "/operator/guarded-run", headers={"X-API-Key": key},
        json={"task": "Calculate 17 * 23", "requested_tools": ["safe_expression"]},
    )
    assert response.status_code == 200 and response.json()["status"] == "BLOCK"
    result = client.get(
        "/operator/operations/" + response.json()["run_id"],
        headers={"Authorization": "Bearer " + key},
    )
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt["status"] == "BLOCKED"
    assert receipt["operation_id"] == response.json()["run_id"]
    assert receipt["stages"]["vantage"]["status"] == "NOT_VERIFIED"
    assert receipt["evidence"]["run_event_count"] == 1
    assert receipt["production_authorized"] is False
