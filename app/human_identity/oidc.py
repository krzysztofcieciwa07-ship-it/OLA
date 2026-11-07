"""Tenant-configured OIDC operator authentication.

Authlib performs the Authorization Code exchange, state/nonce checks and
ID-token cryptographic validation. This module applies OLA's narrower issuer,
audience, algorithm, time, MFA and account-mapping policy after that verified
callback. No provider token is persisted.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.models import TenantIdentityProvider


SUPPORTED_ID_TOKEN_ALGORITHMS = frozenset({"RS256"})
_SECRET_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,62}$")
_ALLOWED_PROFILES = frozenset({"sandbox", "test", "development", "production"})


class OidcLoginRejected(ValueError):
    """Raised when OIDC configuration or verified token claims violate policy."""


@dataclass(frozen=True)
class VerifiedOidcIdentity:
    issuer: str
    subject: str
    auth_time: int | None
    mfa_verified: bool
    acr: str | None
    amr: tuple[str, ...]


def _json_string_set(raw: str | None, *, field_name: str) -> frozenset[str]:
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError) as exc:
        raise OidcLoginRejected(f"invalid tenant OIDC {field_name} policy") from exc
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise OidcLoginRejected(f"tenant OIDC {field_name} policy must be a list of strings")
    return frozenset(value.strip() for value in values)


def _safe_issuer(issuer: str, *, deployment_profile: str) -> str:
    if not isinstance(issuer, str) or not issuer:
        raise OidcLoginRejected("tenant OIDC issuer is missing")
    parsed = urlsplit(issuer)
    if parsed.scheme != "https" or not parsed.netloc:
        local_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not (
            deployment_profile in {"sandbox", "test", "development"}
            and local_host and parsed.scheme == "http" and parsed.netloc
        ):
            raise OidcLoginRejected("OIDC issuer must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OidcLoginRejected("OIDC issuer must be a canonical URL without credentials, query or fragment")
    if parsed.path.endswith("/"):
        raise OidcLoginRejected("OIDC issuer must not end with a slash")
    return issuer


def trusted_public_base_url(*, environ=None, deployment_profile: str | None = None) -> str:
    env = os.environ if environ is None else environ
    profile = (deployment_profile or env.get("OLA_DEPLOYMENT_PROFILE", "sandbox")).strip().lower()
    if profile not in _ALLOWED_PROFILES:
        raise OidcLoginRejected("unknown OLA deployment profile")
    raw = env.get("OLA_PUBLIC_BASE_URL")
    if not isinstance(raw, str) or not raw.strip():
        raise OidcLoginRejected("OLA_PUBLIC_BASE_URL must be configured before OIDC login")
    parsed = urlsplit(raw.strip().rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc:
        local_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not (profile in {"sandbox", "test", "development"} and local_host
                and parsed.scheme == "http" and parsed.netloc):
            raise OidcLoginRejected("public OIDC base URL must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OidcLoginRejected("public OIDC base URL must not include credentials, query or fragment")
    if parsed.path not in {"", "/"}:
        raise OidcLoginRejected("public OIDC base URL must not include a path prefix")
    return raw.strip().rstrip("/")


def expected_redirect_uri(tenant_id: str, *, environ=None, deployment_profile: str | None = None) -> str:
    if not isinstance(tenant_id, str) or not tenant_id:
        raise OidcLoginRejected("tenant_id is required for OIDC redirect URI")
    base = trusted_public_base_url(environ=environ, deployment_profile=deployment_profile)
    return f"{base}/human/oidc/{tenant_id}/callback"


def validate_provider_config(
    provider: TenantIdentityProvider,
    *,
    tenant_id: str,
    deployment_profile: str | None = None,
    environ=None,
) -> dict:
    env = os.environ if environ is None else environ
    profile = (deployment_profile or env.get("OLA_DEPLOYMENT_PROFILE", "sandbox")).strip().lower()
    if profile not in _ALLOWED_PROFILES:
        raise OidcLoginRejected("unknown OLA deployment profile")
    if provider is None or not bool(getattr(provider, "enabled", False)):
        raise OidcLoginRejected("tenant OIDC provider is not enabled")

    issuer = _safe_issuer(provider.issuer, deployment_profile=profile)
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    if provider.discovery_url != discovery_url:
        raise OidcLoginRejected("OIDC discovery URL must be derived from the configured issuer")
    if not isinstance(provider.client_id, str) or not provider.client_id.strip():
        raise OidcLoginRejected("OIDC client_id is not configured")
    secret_ref = provider.client_secret_ref
    if not isinstance(secret_ref, str) or not _SECRET_REF_RE.fullmatch(secret_ref):
        raise OidcLoginRejected("OIDC client secret must be referenced by a safe secret-manager key")
    if provider.id_token_algorithm not in SUPPORTED_ID_TOKEN_ALGORITHMS:
        raise OidcLoginRejected("tenant OIDC ID-token algorithm must be RS256")

    redirect_uri = expected_redirect_uri(
        tenant_id, environ=env, deployment_profile=profile,
    )
    if provider.redirect_uri != redirect_uri:
        raise OidcLoginRejected("tenant OIDC redirect URI does not match the trusted OLA public base URL")

    return {
        "issuer": issuer,
        "discovery_url": discovery_url,
        "client_id": provider.client_id,
        "client_secret_ref": secret_ref,
        "redirect_uri": redirect_uri,
        "id_token_algorithm": provider.id_token_algorithm,
        "mfa_acr_values": _json_string_set(
            provider.mfa_acr_values_json, field_name="acr",
        ),
        "mfa_amr_values": _json_string_set(
            provider.mfa_amr_values_json, field_name="amr",
        ),
    }


def resolve_client_secret(secret_ref: str, *, environ=None) -> str:
    """Resolve a secret reference; plaintext is never accepted from request or DB."""
    env = os.environ if environ is None else environ
    if not isinstance(secret_ref, str) or not _SECRET_REF_RE.fullmatch(secret_ref):
        raise OidcLoginRejected("invalid OIDC client secret reference")
    value = env.get(f"OLA_SECRET_{secret_ref}")
    if not isinstance(value, str) or not value:
        raise OidcLoginRejected("OIDC client secret is unavailable from the configured secret source")
    return value


def create_oidc_client(provider: TenantIdentityProvider, *, tenant_id: str, environ=None):
    """Create an Authlib Starlette client using only tenant-persisted allowlisted config."""
    config = validate_provider_config(provider, tenant_id=tenant_id, environ=environ)
    client_secret = resolve_client_secret(config["client_secret_ref"], environ=environ)
    try:
        from authlib.integrations.starlette_client import OAuth
    except ImportError as exc:
        raise OidcLoginRejected("Authlib Starlette OIDC client is unavailable") from exc

    oauth = OAuth()
    oauth.register(
        name="ola_operator",
        client_id=config["client_id"],
        client_secret=client_secret,
        server_metadata_url=config["discovery_url"],
        client_kwargs={
            "scope": "openid profile",
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )
    return oauth.create_client("ola_operator"), config


def validate_verified_id_token(
    provider,
    claims,
    *,
    signing_algorithm: str,
    nonce_verified: bool,
    now: int | None = None,
    require_step_up: bool = False,
    max_auth_age_seconds: int = 300,
    clock_skew_seconds: int = 0,
) -> VerifiedOidcIdentity:
    """Apply OLA policy to claims already signature-validated by Authlib.

    nonce_verified MUST be true only after Authlib's authorize_access_token()
    completed for the same request/session. It must never come from browser input.
    """
    if not isinstance(claims, dict):
        try:
            claims = dict(claims)
        except (TypeError, ValueError) as exc:
            raise OidcLoginRejected("verified OIDC claims are unavailable") from exc
    if signing_algorithm not in SUPPORTED_ID_TOKEN_ALGORITHMS:
        raise OidcLoginRejected("OIDC ID-token signing algorithm is not allowed")
    configured_alg = getattr(provider, "id_token_algorithm", "RS256")
    if configured_alg != "RS256":
        raise OidcLoginRejected("tenant OIDC ID-token algorithm must be RS256")
    if nonce_verified is not True:
        raise OidcLoginRejected("OIDC nonce was not verified by the Authlib callback")

    issuer = getattr(provider, "issuer", None)
    client_id = getattr(provider, "client_id", None)
    if not isinstance(issuer, str) or not issuer:
        raise OidcLoginRejected("trusted OIDC issuer is missing")
    if not isinstance(client_id, str) or not client_id:
        raise OidcLoginRejected("trusted OIDC audience is missing")
    if claims.get("iss") != issuer:
        raise OidcLoginRejected("OIDC issuer does not match tenant configuration")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise OidcLoginRejected("OIDC subject is missing")

    audience = claims.get("aud")
    if isinstance(audience, str):
        audiences = [audience]
    elif isinstance(audience, list) and audience and all(isinstance(value, str) for value in audience):
        audiences = audience
    else:
        raise OidcLoginRejected("OIDC audience claim is invalid")
    if client_id not in audiences:
        raise OidcLoginRejected("OIDC audience does not include this OLA client")
    authorized_party = claims.get("azp")
    if len(audiences) > 1 and authorized_party != client_id:
        raise OidcLoginRejected("OIDC azp is required and must match the OLA client for multiple audiences")
    if authorized_party is not None and authorized_party != client_id:
        raise OidcLoginRejected("OIDC azp does not match the OLA client")

    current_time = int(time.time()) if now is None else now
    if type(current_time) is not int:
        raise OidcLoginRejected("OIDC validation clock must be an integer timestamp")
    if type(clock_skew_seconds) is not int or not 0 <= clock_skew_seconds <= 120:
        raise OidcLoginRejected("OIDC clock skew policy is invalid")
    for claim_name in ("exp", "iat"):
        claim_value = claims.get(claim_name)
        if type(claim_value) is not int:
            raise OidcLoginRejected(f"OIDC {claim_name} must be an integer NumericDate")
    if claims["exp"] <= current_time - clock_skew_seconds:
        raise OidcLoginRejected("OIDC ID token has expired")
    if claims["iat"] > current_time + clock_skew_seconds:
        raise OidcLoginRejected("OIDC ID token was issued in the future")
    not_before = claims.get("nbf")
    if not_before is not None:
        if type(not_before) is not int or not_before > current_time + clock_skew_seconds:
            raise OidcLoginRejected("OIDC ID token is not yet valid")

    auth_time = claims.get("auth_time")
    if auth_time is not None and type(auth_time) is not int:
        raise OidcLoginRejected("OIDC auth_time must be an integer NumericDate")
    if auth_time is not None and auth_time > current_time + clock_skew_seconds:
        raise OidcLoginRejected("OIDC authentication time is in the future")
    if require_step_up:
        if type(max_auth_age_seconds) is not int or not 30 <= max_auth_age_seconds <= 3600:
            raise OidcLoginRejected("OIDC step-up authentication age policy is invalid")
        if auth_time is None:
            raise OidcLoginRejected("OIDC auth_time is required for high-risk step-up")
        if auth_time < current_time - max_auth_age_seconds:
            raise OidcLoginRejected("OIDC authentication is too old for high-risk step-up")

    acr_values = _json_string_set(
        getattr(provider, "mfa_acr_values_json", "[]"), field_name="acr",
    )
    amr_values = _json_string_set(
        getattr(provider, "mfa_amr_values_json", "[]"), field_name="amr",
    )
    acr = claims.get("acr")
    if acr is not None and not isinstance(acr, str):
        raise OidcLoginRejected("OIDC acr claim must be a string")
    amr = claims.get("amr", [])
    if not isinstance(amr, list) or any(not isinstance(value, str) for value in amr):
        raise OidcLoginRejected("OIDC amr claim must be a list of strings")
    mfa_verified = (
        (isinstance(acr, str) and acr in acr_values)
        or bool(set(amr).intersection(amr_values))
    )

    return VerifiedOidcIdentity(
        issuer=issuer,
        subject=subject,
        auth_time=auth_time,
        mfa_verified=mfa_verified,
        acr=acr,
        amr=tuple(amr),
    )
