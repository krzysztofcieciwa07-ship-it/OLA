"""End-to-end contract for a verified OIDC callback mapped to an active principal."""
import base64
import json
import time
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.human_identity.policy import set_tenant_human_gate_mode
from app.main import app
from app.models import (
    HumanPrincipal,
    HumanSession,
    Tenant,
    TenantIdentityProvider,
)


def _compact_id_token(algorithm="RS256"):
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": algorithm, "typ": "JWT"}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{header}.verified-payload.verified-signature"


def test_oidc_callback_maps_only_active_preprovisioned_principal(monkeypatch):
    tenant_id = str(uuid.uuid4())
    principal_id = str(uuid.uuid4())
    issuer = "https://identity.example.test"
    subject = "oidc-subject-callback-test"
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("OLA_HUMAN_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "sandbox")

    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="oidc-callback-contract"))
        db.commit()
        db.add(TenantIdentityProvider(
            tenant_id=tenant_id,
            issuer=issuer,
            discovery_url=f"{issuer}/.well-known/openid-configuration",
            client_id="ola-operator-client",
            client_secret_ref="OIDC_TEST_CLIENT_SECRET",
            redirect_uri=f"http://localhost:8000/human/oidc/{tenant_id}/callback",
            id_token_algorithm="RS256",
            mfa_acr_values_json='["urn:ola:loa:2"]',
            mfa_amr_values_json='["otp","webauthn"]',
            enabled=True,
        ))
        db.add(HumanPrincipal(
            id=principal_id,
            tenant_id=tenant_id,
            issuer=issuer,
            subject=subject,
            status="ACTIVE",
        ))
        db.commit()

    set_tenant_human_gate_mode(
        tenant_id=tenant_id,
        actor_ref="bootstrap-principal-ref",
        reason="Enable isolated OIDC callback integration test",
        target_mode="OIDC_REQUIRED",
    )

    class FakeAuthlibClient:
        async def authorize_access_token(self, request):
            # The fake client represents Authlib only at this external boundary:
            # it returns claims after a successful state/PKCE/JWKS/nonce validation.
            now = int(time.time())
            return {
                "id_token": _compact_id_token("RS256"),
                "userinfo": {
                    "iss": issuer,
                    "sub": subject,
                    "aud": "ola-operator-client",
                    "exp": now + 300,
                    "iat": now - 10,
                    "nonce": "authlib-already-verified",
                    "auth_time": now - 5,
                    "acr": "urn:ola:loa:2",
                    "amr": ["pwd", "otp"],
                },
                "access_token": "must-never-be-stored",
            }

    def fake_create_oidc_client(provider, *, tenant_id, environ=None):
        return FakeAuthlibClient(), {"redirect_uri": provider.redirect_uri}

    monkeypatch.setattr(
        "app.human_identity.routes.create_oidc_client",
        fake_create_oidc_client,
    )

    client = TestClient(app)
    callback = client.get(f"/human/oidc/{tenant_id}/callback", follow_redirects=True)
    assert callback.status_code == 200
    body = callback.json()
    assert body["authenticated"] is True
    assert body["tenant_id"] == tenant_id
    assert body["principal_ref"] == principal_id
    assert body["mfa_verified"] is True
    assert isinstance(body["csrf_token"], str) and len(body["csrf_token"]) >= 32

    with SessionLocal() as db:
        sessions = db.scalars(
            select(HumanSession).where(HumanSession.tenant_id == tenant_id)
        ).all()
        assert len(sessions) == 1
        assert sessions[0].principal_ref == principal_id
        assert "must-never-be-stored" not in sessions[0].session_data_encrypted
        assert subject not in sessions[0].session_data_encrypted
        assert issuer not in sessions[0].session_data_encrypted


def test_oidc_callback_rejects_unprovisioned_subject_without_creating_principal(monkeypatch):
    tenant_id = str(uuid.uuid4())
    issuer = "https://identity.example.test"
    subject = "never-provisioned-subject"
    monkeypatch.setenv("OLA_PUBLIC_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("OLA_HUMAN_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("OLA_DEPLOYMENT_PROFILE", "sandbox")

    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="oidc-no-auto-provision"))
        db.commit()
        db.add(TenantIdentityProvider(
            tenant_id=tenant_id,
            issuer=issuer,
            discovery_url=f"{issuer}/.well-known/openid-configuration",
            client_id="ola-operator-client",
            client_secret_ref="OIDC_TEST_CLIENT_SECRET",
            redirect_uri=f"http://localhost:8000/human/oidc/{tenant_id}/callback",
            id_token_algorithm="RS256",
            mfa_acr_values_json="[]",
            mfa_amr_values_json="[]",
            enabled=True,
        ))
        db.commit()
    set_tenant_human_gate_mode(
        tenant_id=tenant_id,
        actor_ref="bootstrap-principal-ref",
        reason="Enable no-auto-provision callback contract test",
        target_mode="OIDC_REQUIRED",
    )

    class FakeAuthlibClient:
        async def authorize_access_token(self, request):
            now = int(time.time())
            return {
                "id_token": _compact_id_token("RS256"),
                "userinfo": {
                    "iss": issuer,
                    "sub": subject,
                    "aud": "ola-operator-client",
                    "exp": now + 300,
                    "iat": now - 10,
                    "nonce": "authlib-already-verified",
                },
                "access_token": "temporary-only",
            }

    monkeypatch.setattr(
        "app.human_identity.routes.create_oidc_client",
        lambda provider, *, tenant_id, environ=None: (
            FakeAuthlibClient(), {"redirect_uri": provider.redirect_uri}
        ),
    )

    client = TestClient(app)
    response = client.get(f"/human/oidc/{tenant_id}/callback", follow_redirects=False)
    assert response.status_code == 403
    with SessionLocal() as db:
        principal = db.scalar(select(HumanPrincipal).where(
            HumanPrincipal.tenant_id == tenant_id,
            HumanPrincipal.issuer == issuer,
            HumanPrincipal.subject == subject,
        ))
        assert principal is None
        sessions = db.scalars(
            select(HumanSession).where(HumanSession.tenant_id == tenant_id)
        ).all()
        assert sessions == []
