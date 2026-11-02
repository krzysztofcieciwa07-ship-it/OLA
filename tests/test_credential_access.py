"""Credential authority is distinct from human identity and production permission.

Real disposable SQLite and HTTP routes are exercised. The source observer alone
is a fixture; no claim of physical Windows, real model or person identification.
"""
import importlib
import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_key_crypto import hash_api_key
from app.database import DB_PATH, SessionLocal
from app.hashchain import compute_record_hash, verify_chain
from app.models import ApiKey, EvidenceRecord, Tenant
from conftest import bound_candidate_fields, review_body


main = importlib.import_module("app.main")
pytestmark = pytest.mark.usefixtures("local_binding_source")


def credentials():
    assert {"access_scope", "revoked_at"}.issubset(ApiKey.__table__.columns.keys()), (
        "credential authority and revocation are not implemented"
    )
    tenant, foreign = str(uuid.uuid4()), str(uuid.uuid4())
    keys = {}
    with SessionLocal() as db:
        db.add_all([Tenant(id=tenant, name="access-" + uuid.uuid4().hex),
                    Tenant(id=foreign, name="foreign-access-" + uuid.uuid4().hex)])
        db.flush()
        for label, scope, owner in (
            ("operator", "OLA_CORE", tenant),
            ("other_operator", "OLA_CORE", tenant),
            ("reviewer", "REVIEW_RESULT", tenant),
            ("other_reviewer", "REVIEW_RESULT", tenant),
            ("foreign_reviewer", "REVIEW_RESULT", foreign),
        ):
            raw, credential_id = label + "-" + uuid.uuid4().hex, str(uuid.uuid4())
            db.add(ApiKey(id=credential_id, tenant_id=owner,
                          key_hash=hash_api_key(raw), access_scope=scope))
            keys[label] = {"raw": raw, "id": credential_id, "scope": scope, "tenant": owner}
        db.commit()
    return tenant, keys


def candidate(tenant, requester_id, *, requester_scope="OLA_CORE"):
    run = str(uuid.uuid4())
    payload = {
        "run_id": run, "requester_id": requester_id,
        **bound_candidate_fields(tenant, requester_id, run),
        "status_fields": {"RUNTIME": "VERIFIED", "EVIDENCE": "VERIFIED",
                          "REPLAY_INTEGRITY": "VERIFIED", "POLICY": "VERIFIED",
                          "HUMAN_GATE": "REVIEW", "EXECUTION_ALLOWED": "REVIEW"},
        "candidate_status": "REVIEW",
    }
    if requester_scope is not None:
        payload["requester_credential_scope"] = requester_scope
    else:
        payload.pop("requester_credential_scope", None)
    row = main.append_record(tenant, "decision.candidate", payload)
    return run, review_body(tenant, run, row["record_hash"])


def approve(client, run, body, credential):
    return client.post(f"/nina-run/{run}/approve",
                       headers={"Authorization": "Bearer " + credential["raw"]}, json=body)


def record_count(tenant, record_type=None):
    with SessionLocal() as db:
        query = select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant)
        if record_type:
            query = query.where(EvidenceRecord.record_type == record_type)
        return len(db.scalars(query).all())


def revoke_key(credential_id):
    with SessionLocal() as db:
        db.get(ApiKey, credential_id).revoked_at = 123
        db.commit()


def test_session_reports_stored_scope_without_exposing_credential():
    tenant, keys = credentials()
    client = TestClient(main.app)
    for label in ("operator", "reviewer"):
        credential = keys[label]
        response = client.get("/auth/session", headers={"X-API-Key": credential["raw"]})
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "tenant_id": tenant,
                                   "credential_id": credential["id"], "scope": credential["scope"]}
        assert credential["raw"] not in response.text


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/control/overview", None),
    ("GET", "/control/runs/00000000-0000-0000-0000-000000000000", None),
    ("GET", "/evidence/00000000-0000-0000-0000-000000000000", None),
    ("POST", "/chat", {"messages": [{"role": "user", "content": "hello"}]}),
    ("POST", "/checkout", {"task": "test"}),
    ("POST", "/evidence", {"record_type": "generic", "payload": {"must": "not append"}}),
    ("POST", "/audit", {"task": "test"}),
    ("POST", "/agent-run", {"task": "test", "requested_tools": []}),
    ("POST", "/nina-run", {"task": "17 * 23", "requested_tools": ["safe_expression"]}),
    ("POST", "/business-invoice-run", {"invoice": {}}),
])
def test_reviewer_cannot_use_core_routes(method, path, payload):
    tenant, keys = credentials()
    before = record_count(tenant)
    response = TestClient(main.app).request(
        method, path, headers={"X-API-Key": keys["reviewer"]["raw"]}, json=payload,
    )
    assert response.status_code == 403, response.text
    assert record_count(tenant) == before


def test_only_reviewer_scope_may_approve_and_scope_is_evidence_bound():
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    client = TestClient(main.app)
    assert approve(client, run, body, keys["operator"]).status_code == 403
    assert approve(client, run, body, keys["other_operator"]).status_code == 403
    assert approve(client, run, body, keys["foreign_reviewer"]).status_code == 404
    response = approve(client, run, body, keys["reviewer"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["approver_credential_scope"] == "REVIEW_RESULT"
    assert result["assurance"] == "UNKNOWN" and result["production_eligible"] is False
    with SessionLocal() as db:
        row = db.scalar(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant, EvidenceRecord.record_type == "human.approval"))
        payload = json.loads(row.payload_json)
        assert payload["requester_credential_scope"] == "OLA_CORE"
        assert payload["approver_credential_scope"] == "REVIEW_RESULT"
        assert all(key["raw"] not in row.payload_json for key in keys.values())
    for label in ("operator", "reviewer"):
        current = client.get(f"/nina-run/{run}/approval",
                             headers={"Authorization": "Bearer " + keys[label]["raw"]})
        assert current.json()["status"] == "APPROVED"
        assert current.json()["reviewer_credential_status"] == "ACTIVE"


@pytest.mark.parametrize("scope", [None, "REVIEW_RESULT", "ADMIN"])
def test_candidate_with_missing_or_noncore_scope_is_not_promoted(scope):
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"], requester_scope=scope)
    response = approve(TestClient(main.app), run, body, keys["reviewer"])
    assert response.status_code == 409, response.text
    assert record_count(tenant, "human.approval") == 0


@pytest.mark.parametrize("label", ["operator", "reviewer"])
def test_revoked_credential_is_denied_in_key_and_bearer_auth(label):
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    credential = keys[label]
    revoke_key(credential["id"])
    client = TestClient(main.app)
    assert client.get("/auth/session", headers={"X-API-Key": credential["raw"]}).status_code == 401
    assert client.get(f"/nina-run/{run}/approval",
                      headers={"Authorization": "Bearer " + credential["raw"]}).status_code == 401
    assert approve(client, run, body, credential).status_code == 401
    assert record_count(tenant, "human.approval") == 0


@pytest.mark.parametrize("change,expected", [
    ("revoke", "REVOKED"), ("delete", "MISSING"),
    ("scope", "INVALID_SCOPE"), ("tenant", "TENANT_MISMATCH"),
])
def test_current_approval_blocks_inactive_or_reassigned_reviewer(change, expected):
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    client = TestClient(main.app)
    response = approve(client, run, body, keys["reviewer"])
    assert response.status_code == 200
    with SessionLocal() as db:
        key = db.get(ApiKey, keys["reviewer"]["id"])
        if change == "revoke": key.revoked_at = 123
        elif change == "delete": db.delete(key)
        elif change == "scope": key.access_scope = "OLA_CORE"
        elif change == "tenant": key.tenant_id = keys["foreign_reviewer"]["tenant"]
        db.commit()
    current = client.get(f"/nina-run/{run}/approval",
                         headers={"Authorization": "Bearer " + keys["operator"]["raw"]})
    assert current.status_code == 200
    assert current.json()["status"] == "BLOCKED"
    assert current.json()["reviewer_credential_status"] == expected
    assert current.json()["production_eligible"] is False
    assert record_count(tenant, "human.approval") == 1


def test_unknown_stored_scope_is_fail_closed():
    _, keys = credentials()
    with sqlite3.connect(DB_PATH) as raw:
        raw.execute("PRAGMA ignore_check_constraints = ON")
        raw.execute("UPDATE api_keys SET access_scope='ADMIN' WHERE id=?", (keys["operator"]["id"],))
    try:
        response = TestClient(main.app).get("/auth/session", headers={"X-API-Key": keys["operator"]["raw"]})
        assert response.status_code == 503
    finally:
        with sqlite3.connect(DB_PATH) as raw:
            raw.execute("UPDATE api_keys SET access_scope='OLA_CORE' WHERE id=?", (keys["operator"]["id"],))


def test_revoked_requester_cannot_be_promoted_through_active_reviewer():
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    revoke_key(keys["operator"]["id"])
    response = approve(TestClient(main.app), run, body, keys["reviewer"])
    assert response.status_code == 409, response.text
    assert record_count(tenant, "human.approval") == 0


@pytest.mark.parametrize("operation", ["approve", "revoke-approval"])
def test_revocation_after_preflight_auth_is_rechecked_under_writer_lock(monkeypatch, operation):
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    client = TestClient(main.app)
    if operation == "revoke-approval":
        approved = approve(client, run, body, keys["reviewer"])
        assert approved.status_code == 200
        body = {"human_approval_digest": approved.json()["human_approval_digest"]}
    boundary = getattr(main, "reviewer_bearer_identity", None)
    assert callable(boundary), "reviewer transaction reauthentication is not implemented"
    called = False
    def revoke_after_authenticated(authorization, **kwargs):
        nonlocal called
        identity = boundary(authorization, **kwargs)
        if not called and kwargs.get("db") is None:
            called = True
            revoke_key(keys["reviewer"]["id"])
        return identity
    monkeypatch.setattr(main, "reviewer_bearer_identity", revoke_after_authenticated)
    path = f"/nina-run/{run}/approve" if operation == "approve" else f"/nina-run/{run}/approval/revoke"
    response = client.post(path, headers={"Authorization": "Bearer " + keys["reviewer"]["raw"]}, json=body)
    assert called
    assert response.status_code == 401, response.text
    assert record_count(tenant, "human.approval" if operation == "approve" else "human.approval.revoked") == 0


def test_reviewer_scope_is_checked_again_before_approval_write(monkeypatch):
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    boundary = getattr(main, "reviewer_bearer_identity", None)
    assert callable(boundary), "reviewer transaction reauthentication is not implemented"
    changed = False
    def change_after_authenticated(authorization, **kwargs):
        nonlocal changed
        identity = boundary(authorization, **kwargs)
        if not changed and kwargs.get("db") is None:
            changed = True
            with SessionLocal() as db:
                db.get(ApiKey, keys["reviewer"]["id"]).access_scope = "OLA_CORE"
                db.commit()
        return identity
    monkeypatch.setattr(main, "reviewer_bearer_identity", change_after_authenticated)
    response = approve(TestClient(main.app), run, body, keys["reviewer"])
    assert changed and response.status_code == 403
    assert record_count(tenant, "human.approval") == 0


def test_generated_candidate_records_core_scope_before_review(monkeypatch):
    tenant, keys = credentials()
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.setenv("OLA_LLM_PROVIDER", "local")
    response = TestClient(main.app).post(
        "/nina-run", headers={"X-API-Key": keys["operator"]["raw"]},
        json={"task": "Calculate 17 * 23", "requested_tools": ["safe_expression", "local_mcp_tool_registry.sha256"]},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        row = db.scalar(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant, EvidenceRecord.record_type == "decision.candidate"))
        assert row is not None
        assert json.loads(row.payload_json)["requester_credential_scope"] == "OLA_CORE"


def test_legacy_approval_without_scope_attestation_is_blocked_even_if_rehashed():
    tenant, keys = credentials()
    run, body = candidate(tenant, keys["operator"]["id"])
    response = approve(TestClient(main.app), run, body, keys["reviewer"])
    assert response.status_code == 200
    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq)).all()
        chain = [{name: getattr(row, name) for name in (
            "id", "tenant_id", "seq", "prev_hash", "record_hash", "record_type", "hash_version", "payload_json")}
                 for row in rows]
    payload = json.loads(chain[-1]["payload_json"])
    payload.pop("approver_credential_scope")
    chain[-1]["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    row = chain[-1]
    row["record_hash"] = compute_record_hash(
        tenant, row["seq"], row["prev_hash"], row["payload_json"],
        record_id=row["id"], record_type=row["record_type"], hash_version=2,
    )
    assert verify_chain(chain)[0]
    assert main.review_state(chain, run)[0] == "BLOCKED"
