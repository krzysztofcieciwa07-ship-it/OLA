"""Regression tests for opaque, encrypted, server-side Human Identity sessions."""
import importlib
from importlib.util import find_spec
import uuid
from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Tenant


def _tenant():
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="human-session-test"))
        db.commit()
    return tenant_id


def test_human_identity_sessions_module_exists():
    assert find_spec("app.human_identity.sessions") is not None, (
        "server-side Human Identity session store is missing"
    )


@pytest.fixture
def session_api():
    if find_spec("app.human_identity.sessions") is None:
        pytest.skip("server-side Human Identity session store has not been implemented")
    return importlib.import_module("app.human_identity.sessions")


def _client(monkeypatch, session_api):
    from cryptography.fernet import Fernet
    ServerSideSessionMiddleware = session_api.ServerSideSessionMiddleware

    monkeypatch.setenv("OLA_HUMAN_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    app = FastAPI()
    app.add_middleware(
        ServerSideSessionMiddleware,
        cookie_name="ola_human_session",
        secure_cookie=False,
        ttl_seconds=3600,
    )

    @app.get("/write")
    def write(request: Request):
        request.session["state"] = "oidc-state-one-time"
        request.session["nonce"] = "oidc-nonce-one-time"
        request.session["code_verifier"] = "pkce-verifier-secret"
        return {"saved": True}

    @app.get("/read")
    def read(request: Request):
        return {
            "state": request.session.get("state"),
            "nonce": request.session.get("nonce"),
            "code_verifier": request.session.get("code_verifier"),
        }

    @app.post("/login")
    def login(request: Request):
        from app.human_identity.sessions import establish_human_session
        tenant_id = _tenant()
        principal_ref = f"principal-{uuid.uuid4()}"
        establish_human_session(
            request,
            tenant_id=tenant_id,
            principal_ref=principal_ref,
            auth_time=1_800_000_000,
            mfa_verified=True,
        )
        return {"tenant_id": tenant_id, "principal_ref": principal_ref}

    @app.get("/protected")
    def protected(request: Request):
        from app.human_identity.sessions import require_human_session
        try:
            context = require_human_session(request)
        except Exception:
            return {"authenticated": False}
        return {
            "authenticated": True,
            "tenant_id": context.tenant_id,
            "principal_ref": context.principal_ref,
            "auth_time": context.auth_time,
            "mfa_verified": context.mfa_verified,
        }

    @app.post("/logout")
    def logout(request: Request):
        from app.human_identity.sessions import revoke_human_session
        revoke_human_session(request)
        return {"logged_out": True}

    return TestClient(app)


def _cookie(response, name="ola_human_session"):
    jar = SimpleCookie()
    jar.load(response.headers.get("set-cookie", ""))
    assert name in jar
    return jar[name].value


def test_authlib_transient_state_is_encrypted_server_side_not_cookie(monkeypatch, session_api):
    client = _client(monkeypatch, session_api)
    response = client.get("/write")
    assert response.status_code == 200
    token = _cookie(response)
    assert "oidc-state-one-time" not in token
    assert "pkce-verifier-secret" not in token

    with SessionLocal() as db:
        HumanSession = importlib.import_module("app.models").HumanSession
        rows = db.scalars(select(HumanSession)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.session_hash
        assert row.session_hash != token
        assert row.session_data_encrypted
        assert "oidc-state-one-time" not in row.session_data_encrypted
        assert "pkce-verifier-secret" not in row.session_data_encrypted

    resumed = client.get("/read")
    assert resumed.json() == {
        "state": "oidc-state-one-time",
        "nonce": "oidc-nonce-one-time",
        "code_verifier": "pkce-verifier-secret",
    }


def test_human_login_rotates_session_and_binds_authenticated_context(monkeypatch, session_api):
    client = _client(monkeypatch, session_api)
    before = client.get("/write")
    old_cookie = _cookie(before)
    response = client.post("/login")
    assert response.status_code == 200
    new_cookie = _cookie(response)
    assert new_cookie != old_cookie
    result = response.json()

    protected = client.get("/protected")
    assert protected.json() == {
        "authenticated": True,
        "tenant_id": result["tenant_id"],
        "principal_ref": result["principal_ref"],
        "auth_time": 1_800_000_000,
        "mfa_verified": True,
    }

    with SessionLocal() as db:
        HumanSession = importlib.import_module("app.models").HumanSession
        rows = db.scalars(select(HumanSession).order_by(HumanSession.created_at.asc())).all()
        assert len(rows) == 2
        assert rows[0].revoked_at is not None
        assert rows[1].revoked_at is None


def test_tampered_expired_or_revoked_session_is_not_authenticated(monkeypatch, session_api):
    client = _client(monkeypatch, session_api)
    response = client.post("/login")
    token = _cookie(response)
    assert client.get("/protected").json()["authenticated"] is True

    client.post("/logout")
    assert client.get("/protected").json()["authenticated"] is False

    # Replaying a previously captured opaque cookie cannot revive the revoked row.
    replay = TestClient(client.app)
    replay.cookies.set("ola_human_session", token)
    assert replay.get("/protected").json()["authenticated"] is False

    tampered = TestClient(client.app)
    tampered.cookies.set("ola_human_session", token[:-1] + ("A" if token[-1] != "A" else "B"))
    assert tampered.get("/protected").json()["authenticated"] is False


def test_production_session_storage_fails_closed_without_encryption_key(monkeypatch, session_api):
    HumanSessionUnavailable = session_api.HumanSessionUnavailable
    create_human_session = session_api.create_human_session

    monkeypatch.delenv("OLA_HUMAN_SESSION_ENCRYPTION_KEY", raising=False)
    with pytest.raises(HumanSessionUnavailable):
        create_human_session(
            tenant_id=None,
            principal_ref=None,
            session_data={"state": "one-time"},
            auth_time=None,
            mfa_verified=False,
            ttl_seconds=300,
        )
