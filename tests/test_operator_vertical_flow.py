"""HTTP-level regression for operator -> NINA -> IGOR -> Human Gate.

Test keys and tenant records are isolated in conftest's throwaway SQLite.
"""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant


def _identity(*, tenant=None):
    tenant = tenant or str(uuid.uuid4())
    raw_key = "operator-e2e-" + uuid.uuid4().hex
    with SessionLocal() as db:
        if db.get(Tenant, tenant) is None:
            db.add(Tenant(id=tenant, name="operator E2E synthetic tenant"))
            db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant,
                      key_hash=api_key_fingerprint(raw_key)))
        db.commit()
    return tenant, raw_key


def test_real_operator_flow_requires_second_identity_and_verifiable_evidence(monkeypatch):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", "a" * 40)
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    tenant, requester_key = _identity()
    _, reviewer_key = _identity(tenant=tenant)
    _, other_tenant_key = _identity()
    client = TestClient(app)

    result = client.post("/nina-run",
                         headers={"X-API-Key": requester_key},
                         json={"task": "Calculate 17 * 23 and return verified result.",
                               "requested_tools": ["safe_expression"],
                               "human_approved": True})
    assert result.status_code == 200, result.text
    candidate = result.json()
    assert candidate["status"] == "REVIEW", candidate
    assert candidate["igor"]["status"] == "VERIFIED", candidate
    assert candidate["replay_verification"]["status"] == "VERIFIED", candidate
    assert candidate["status_fields"]["EXECUTION_ALLOWED"] == "REVIEW"

    run_id = candidate["run_id"]
    tip = candidate["tip_hash"]

    # A browser-provided approval flag and self-approval never authorize.
    self_approval = client.post(
        f"/nina-run/{run_id}/approve",
        headers={"Authorization": "Bearer " + requester_key},
        json={"tip_hash": tip, "reason": "I approve myself"})
    assert self_approval.status_code == 403, self_approval.text
    foreign = client.post(
        f"/nina-run/{run_id}/approve",
        headers={"Authorization": "Bearer " + other_tenant_key},
        json={"tip_hash": tip, "reason": "another tenant"})
    assert foreign.status_code in (403, 404, 409), foreign.text

    approved = client.post(
        f"/nina-run/{run_id}/approve",
        headers={"Authorization": "Bearer " + reviewer_key},
        json={"tip_hash": tip, "reason": "Independent review of local synthetic task"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "VERIFIED"

    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq.asc())).all()
    ledger = [
        {"id": r.id, "tenant_id": r.tenant_id, "seq": r.seq,
         "record_type": r.record_type, "payload_json": r.payload_json,
         "prev_hash": r.prev_hash, "record_hash": r.record_hash} for r in rows
    ]
    assert verify_chain(ledger)[0]
    approvals = [r for r in ledger if r["record_type"] == "human.approval"]
    assert len(approvals) == 1
    assert approved.json()["record_id"] == approvals[0]["id"]

    # A second approval is a replay, not a second valid decision.
    repeat = client.post(
        f"/nina-run/{run_id}/approve",
        headers={"Authorization": "Bearer " + reviewer_key},
        json={"tip_hash": approved.json()["tip_hash"], "reason": "repeat"})
    assert repeat.status_code == 409, repeat.text
