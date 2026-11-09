"""Public contract tests for OLA human OIDC routes."""
import uuid

from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey, Tenant


def _tenant_with_api_key():
    tenant_id = str(uuid.uuid4())
    raw_key = f"api-key-must-not-authenticate-a-human-{uuid.uuid4()}"
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="oidc-human-route-test"))
        db.commit()
        db.add(ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(raw_key),
            role="tenant",
        ))
        db.commit()
    return tenant_id, raw_key


def test_operator_session_endpoint_does_not_accept_api_key_as_human_identity():
    _tenant_id, raw_key = _tenant_with_api_key()
    response = TestClient(app).get(
        "/human/session",
        headers={"X-API-Key": raw_key},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "authenticated Human Identity session is required"


def test_oidc_login_requires_persistent_oidc_policy_and_configured_provider():
    from app.human_identity.policy import set_tenant_human_gate_mode

    tenant_id, _raw_key = _tenant_with_api_key()
    client = TestClient(app)

    # A legacy tenant cannot enter the operator OIDC flow until it has
    # explicitly and durably enabled the one-way identity policy.
    response = client.get(f"/human/oidc/{tenant_id}/login")
    assert response.status_code == 403

    set_tenant_human_gate_mode(
        tenant_id=tenant_id,
        actor_ref="bootstrap-principal-ref",
        reason="Enable OIDC for isolated route contract test",
        target_mode="OIDC_REQUIRED",
    )
    response = client.get(f"/human/oidc/{tenant_id}/login")
    assert response.status_code == 403
    assert response.json()["detail"] == "tenant OIDC provider is not enabled"


def test_oidc_routes_are_mounted_in_the_application():
    route_paths = {route.path for route in app.routes}
    assert "/human/oidc/{tenant_id}/login" in route_paths
    assert "/human/oidc/{tenant_id}/callback" in route_paths
    assert "/human/session" in route_paths
    assert "/human/logout" in route_paths


def test_tenant_role_change_routes_are_mounted_and_do_not_accept_api_keys():
    from app.human_identity.policy import set_tenant_human_gate_mode

    tenant_id, raw_key = _tenant_with_api_key()
    set_tenant_human_gate_mode(
        tenant_id=tenant_id,
        actor_ref="bootstrap-principal-ref",
        reason="Enable OIDC for role management route contract test",
        target_mode="OIDC_REQUIRED",
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {raw_key}", "X-API-Key": raw_key}
    payload = {
        "target_principal_id": "target-principal",
        "role": "report_reviewer",
        "operation": "GRANT",
        "reason": "Test API keys must not manage human roles",
    }

    request = client.post(
        f"/human/tenants/{tenant_id}/role-changes",
        headers=headers,
        json=payload,
    )
    assert request.status_code == 401
    assert request.json()["detail"] == "authenticated Human Identity session is required"

    approval = client.post(
        f"/human/tenants/{tenant_id}/role-changes/change-1/approve",
        headers=headers,
        json={"reason": "Test API keys must not approve human role changes"},
    )
    assert approval.status_code == 401
    assert approval.json()["detail"] == "authenticated Human Identity session is required"


def test_tenant_role_change_routes_are_registered():
    route_paths = {route.path for route in app.routes}
    assert "/human/tenants/{tenant_id}/role-changes" in route_paths
    assert "/human/tenants/{tenant_id}/role-changes/{change_id}/approve" in route_paths
