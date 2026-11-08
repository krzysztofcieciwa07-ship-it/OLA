"""Tenant identity on /evidence/tip must come only from the authenticated API key."""

import uuid

from fastapi.testclient import TestClient

from app import main
from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.hashchain import GENESIS_HASH
from app.main import app
from app.models import ApiKey, Tenant


def _client_with_two_tenants():
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    key_a = "evidence-tip-a-" + uuid.uuid4().hex
    key_b = "evidence-tip-b-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add_all([
            Tenant(id=tenant_a, name="evidence-tip-tenant-a"),
            Tenant(id=tenant_b, name="evidence-tip-tenant-b"),
        ])
        db.add_all([
            ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_a,
                key_hash=api_key_fingerprint(key_a),
            ),
            ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_b,
                key_hash=api_key_fingerprint(key_b),
            ),
        ])
        db.commit()
    return TestClient(app), tenant_a, tenant_b, key_a, key_b


def test_evidence_tip_returns_identity_bound_to_authenticated_api_key():
    client, tenant_a, _, key_a, _ = _client_with_two_tenants()

    response = client.get("/evidence/tip", headers={"X-API-Key": key_a})

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == tenant_a
    assert response.json()["record_count"] == 0
    assert response.json()["tip_hash"] == GENESIS_HASH


def test_evidence_tip_does_not_disclose_another_tenants_chain():
    client, tenant_a, tenant_b, key_a, key_b = _client_with_two_tenants()
    main.append_record(tenant_a, "test.tenant_a_only", {"marker": "private-to-a"})

    response_a = client.get("/evidence/tip", headers={"X-API-Key": key_a})
    response_b = client.get("/evidence/tip", headers={"X-API-Key": key_b})

    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text
    assert response_a.json()["tenant_id"] == tenant_a
    assert response_a.json()["record_count"] == 1
    assert response_a.json()["tip_hash"] != GENESIS_HASH
    assert response_b.json()["tenant_id"] == tenant_b
    assert response_b.json()["record_count"] == 0
    assert response_b.json()["tip_hash"] == GENESIS_HASH


def test_evidence_tip_ignores_caller_selected_tenant_query_parameter():
    client, tenant_a, tenant_b, key_a, _ = _client_with_two_tenants()

    response = client.get(
        "/evidence/tip",
        params={"tenant_id": tenant_b},
        headers={"X-API-Key": key_a},
    )

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == tenant_a
    assert response.json()["tenant_id"] != tenant_b


def test_evidence_tip_requires_valid_api_key():
    client, _, _, _, _ = _client_with_two_tenants()

    missing = client.get("/evidence/tip")
    invalid = client.get(
        "/evidence/tip",
        headers={"X-API-Key": "invalid-evidence-tip-key"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
