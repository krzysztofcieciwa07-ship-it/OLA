"""Real readback through OLA evidence, not frontend-supplied verification flags."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, Tenant


def _key(tenant_id=None):
    tenant_id = tenant_id or str(uuid.uuid4())
    raw = "receipt-test-" + uuid.uuid4().hex
    key_id = str(uuid.uuid4())
    with SessionLocal() as db:
        if db.get(Tenant, tenant_id) is None:
            db.add(Tenant(id=tenant_id, name="receipt synthetic test"))
            db.flush()
        db.add(ApiKey(id=key_id, tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(raw)))
        db.commit()
    return tenant_id, key_id, raw


def test_operation_readback_scopes_identity_rechecks_igor_and_never_claims_vantage(monkeypatch):
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "e" * 40)
    tenant, requester_id, requester = _key()
    _, reviewer_id, reviewer = _key(tenant)
    _, _, outsider = _key()
    client = TestClient(app)

    resp = client.post("/nina-run", headers={"X-API-Key": requester},
                       json={"task": "Calculate 17 * 23 and return verified result.",
                             "requested_tools": ["safe_expression"]})
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["status"] == "REVIEW", run

    url = "/operator/operations/" + run["run_id"]
    before = client.get(url, headers={"Authorization": "Bearer " + requester})
    assert before.status_code == 200, before.text
    item = before.json()
    assert item["schema"] == "ola.operation.v1"
    assert item["operation_id"] == run["run_id"]
    assert item["correlation_id"] == run["run_id"]
    assert item["tenant_id"] == tenant
    assert item["actor"] == {"kind": "user", "subject_id": requester_id}
    assert item["source_commit"] == "e" * 40
    assert item["status"] == "REVIEW_REQUIRED"
    assert item["stages"]["igor"]["status"] == "VERIFIED_LOCAL_EVIDENCE"
    assert item["stages"]["vantage"]["status"] == "NOT_CONNECTED"
    assert item["stages"]["codex_bridge"]["status"] == "NOT_CONNECTED"
    assert item["stages"]["codex_bridge"]["operation_id"] == run["run_id"]
    assert item["stages"]["nova"]["status"] == "NOT_CONNECTED"
    assert item["stages"]["nova"]["operation_id"] == run["run_id"]
    assert item["stages"]["execution"]["mode"] == "local_deterministic_model"
    assert item["evidence"]["chain_tip"] == run["tip_hash"]
    assert item["evidence"]["run_event_count"] > 0
    assert item["system_acceptance"] == "NOT_VERIFIED"
    assert item["production_authorized"] is False
    assert "verified" not in item or item["verified"] is False
    assert requester not in before.text and reviewer not in before.text

    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer " + outsider}).status_code == 404
    assert client.get("/operator/operations/not-a-uuid",
                      headers={"Authorization": "Bearer " + requester}).status_code == 400

    approved = client.post("/nina-run/" + run["run_id"] + "/approve",
                           headers={"Authorization": "Bearer " + reviewer},
                           json={"tip_hash": run["tip_hash"], "reason": "reviewed synthetic run"})
    assert approved.status_code == 200, approved.text

    after = client.get(url, headers={"Authorization": "Bearer " + reviewer})
    assert after.status_code == 200, after.text
    receipt = after.json()
    assert receipt["status"] == "APPROVED_FOR_REVIEW_ONLY"
    assert receipt["reviewer_id"] == reviewer_id
    assert receipt["evidence"]["chain_tip"] == approved.json()["tip_hash"]
    assert receipt["evidence"]["chain_tip"] != run["tip_hash"]
    assert receipt["stages"]["vantage"]["status"] == "NOT_CONNECTED"
    assert receipt["production_authorized"] is False


def test_operator_page_is_a_same_origin_entry_point_without_credentials():
    response = TestClient(app).get("/operator")
    assert response.status_code == 200
    assert "/operator/operations/" in response.text
    assert "localStorage" not in response.text
    assert "sessionStorage" not in response.text
    assert "<script src=\"https://" not in response.text
