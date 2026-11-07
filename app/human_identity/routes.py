"""Human OIDC login/callback and server-side operator session routes."""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import re
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.database import SessionLocal, append_evidence_atomic
from app.models import HumanPrincipal, TenantIdentityProvider
from app.human_identity.oidc import (
    OidcLoginRejected,
    create_oidc_client,
    trusted_public_base_url,
    validate_verified_id_token,
)
from app.human_identity.policy import (
    HumanIdentityPolicyRejected,
    require_human_identity_mode,
)
from app.human_identity.sessions import (
    AUTH_SESSION_KEY,
    HumanSessionRejected,
    establish_human_session,
    require_human_session,
    revoke_human_session,
)


router = APIRouter()
_TENANT_PATH_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _deployment_profile() -> str:
    return os.environ.get("OLA_DEPLOYMENT_PROFILE", "sandbox").strip().lower()


def _provider_for_tenant(tenant_id: str) -> TenantIdentityProvider:
    with SessionLocal() as db:
        provider = db.get(TenantIdentityProvider, tenant_id)
        if provider is None or not provider.enabled:
            raise HTTPException(status_code=403, detail="tenant OIDC provider is not enabled")
        # Return a detached immutable snapshot; routes must not mutate provider settings.
        values = {
            column.name: getattr(provider, column.name)
            for column in TenantIdentityProvider.__table__.columns
        }
    return TenantIdentityProvider(**values)


def _require_oidc_policy(tenant_id: str) -> None:
    try:
        mode = require_human_identity_mode(
            tenant_id=tenant_id,
            deployment_profile=_deployment_profile(),
        )
    except HumanIdentityPolicyRejected as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc
    if mode != "OIDC_REQUIRED":
        raise HTTPException(
            status_code=403,
            detail="operator Human Gate requires the tenant's persistent OIDC_REQUIRED policy",
        )


def id_token_signing_algorithm(compact_id_token: str) -> str:
    """Read only the JOSE header; Authlib must verify signature before claims are trusted."""
    if not isinstance(compact_id_token, str):
        raise OidcLoginRejected("OIDC ID token is unavailable")
    parts = compact_id_token.split(".")
    if len(parts) != 3 or not all(parts):
        raise OidcLoginRejected("OIDC ID token compact serialization is invalid")
    try:
        raw_header = base64.urlsafe_b64decode(
            parts[0] + ("=" * (-len(parts[0]) % 4))
        )
        header = json.loads(raw_header.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise OidcLoginRejected("OIDC ID token protected header is invalid") from exc
    if not isinstance(header, dict) or not isinstance(header.get("alg"), str):
        raise OidcLoginRejected("OIDC ID token algorithm header is missing")
    return header["alg"]


def verify_human_csrf(request: Request, csrf_token: str | None) -> None:
    auth = request.session.get(AUTH_SESSION_KEY)
    expected = auth.get("csrf_token") if isinstance(auth, dict) else None
    supplied = csrf_token
    origin = request.headers.get("origin")
    try:
        trusted_base = trusted_public_base_url(deployment_profile=_deployment_profile())
    except OidcLoginRejected as exc:
        raise HTTPException(status_code=503, detail="trusted OLA origin is unavailable") from exc
    expected_origin = urlsplit(trusted_base)
    supplied_origin = urlsplit(origin or "")
    origin_matches = (
        supplied_origin.scheme == expected_origin.scheme
        and supplied_origin.netloc == expected_origin.netloc
        and supplied_origin.path in {"", "/"}
        and not supplied_origin.query
        and not supplied_origin.fragment
    )
    if (
        not isinstance(expected, str)
        or not isinstance(supplied, str)
        or not hmac.compare_digest(expected, supplied)
        or not origin_matches
    ):
        raise HTTPException(status_code=403, detail="Human Identity CSRF or origin validation failed")


@router.get("/human/oidc/{tenant_id}/login")
async def human_oidc_login(tenant_id: str, request: Request):
    if not _TENANT_PATH_RE.fullmatch(tenant_id):
        raise HTTPException(status_code=400, detail="invalid tenant identity path")
    _require_oidc_policy(tenant_id)
    provider = _provider_for_tenant(tenant_id)
    try:
        client, config = create_oidc_client(
            provider,
            tenant_id=tenant_id,
        )
        return await client.authorize_redirect(request, config["redirect_uri"])
    except OidcLoginRejected as exc:
        raise HTTPException(status_code=503, detail="tenant OIDC login is not safely configured") from exc
    except Exception as exc:
        # Do not expose provider metadata, secrets, token responses or callback state.
        raise HTTPException(status_code=503, detail="tenant OIDC authorization is unavailable") from exc


@router.get("/human/oidc/{tenant_id}/callback")
async def human_oidc_callback(tenant_id: str, request: Request):
    if not _TENANT_PATH_RE.fullmatch(tenant_id):
        raise HTTPException(status_code=400, detail="invalid tenant identity path")
    _require_oidc_policy(tenant_id)
    provider = _provider_for_tenant(tenant_id)
    try:
        client, _config = create_oidc_client(provider, tenant_id=tenant_id)
        # Authlib verifies authorization state, PKCE, ID-token signature/JWKS,
        # issuer, audience, expiry and nonce before exposing token['userinfo'].
        token = await client.authorize_access_token(request)
        compact_id_token = token.get("id_token") if isinstance(token, dict) else None
        claims = token.get("userinfo") if isinstance(token, dict) else None
        if claims is None:
            raise OidcLoginRejected("OIDC verified user claims are unavailable")
        claims = dict(claims)
        algorithm = id_token_signing_algorithm(compact_id_token)
        identity = validate_verified_id_token(
            provider,
            claims,
            signing_algorithm=algorithm,
            nonce_verified=True,
        )
    except OidcLoginRejected as exc:
        raise HTTPException(status_code=401, detail="OIDC identity verification failed") from exc
    except Exception as exc:
        # Callback failures are fail-closed; never log or echo tokens or raw claims.
        raise HTTPException(status_code=401, detail="OIDC callback could not be verified") from exc

    with SessionLocal() as db:
        principal = db.scalar(select(HumanPrincipal).where(
            HumanPrincipal.tenant_id == tenant_id,
            HumanPrincipal.issuer == identity.issuer,
            HumanPrincipal.subject == identity.subject,
            HumanPrincipal.status == "ACTIVE",
        ))
        if principal is None:
            raise HTTPException(
                status_code=403,
                detail="OIDC account has no active, explicitly provisioned tenant membership",
            )
        principal_ref = principal.id
        principal.last_authenticated_at = int(time.time())
        db.commit()

    try:
        # The successful operator authentication is part of the tenant's
        # append-only evidence chain. Store only the pseudonymous principal ref.
        append_evidence_atomic(
            tenant_id,
            "human.operator_authenticated",
            {
                "principal_ref": principal_ref,
                "auth_time": identity.auth_time,
                "mfa_verified": identity.mfa_verified,
                "authenticated_at": int(time.time()),
                "decision": "AUTHENTICATED",
            },
            producer_id="ola_runtime",
        )
        establish_human_session(
            request,
            tenant_id=tenant_id,
            principal_ref=principal_ref,
            auth_time=identity.auth_time,
            mfa_verified=identity.mfa_verified,
        )
    except (HumanSessionRejected, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="secure Human Identity session could not be established") from exc
    return RedirectResponse(url="/human/session", status_code=303)


@router.get("/human/session")
def human_session_status(request: Request):
    try:
        context = require_human_session(request)
    except HumanSessionRejected as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc
    auth = request.session.get(AUTH_SESSION_KEY, {})
    response = {
        "authenticated": True,
        "tenant_id": context.tenant_id,
        "principal_ref": context.principal_ref,
        "auth_time": context.auth_time,
        "mfa_verified": context.mfa_verified,
        "csrf_token": auth.get("csrf_token") if isinstance(auth, dict) else None,
    }
    return response


@router.post("/human/logout")
def human_session_logout(
    request: Request,
    x_ola_csrf: str | None = Header(default=None),
):
    try:
        require_human_session(request)
    except HumanSessionRejected as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc
    verify_human_csrf(request, x_ola_csrf)
    revoke_human_session(request)
    return {"status": "LOGGED_OUT"}
