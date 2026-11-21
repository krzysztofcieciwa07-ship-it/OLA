"""Fail-closed OIDC Subject verification foundation for OLA Human Gate."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import threading
import time
from urllib.parse import urlsplit

import httpx
import jwt


class ApprovalIdentityError(Exception):
    """Identity token or configuration could not be verified."""


@dataclass(frozen=True)
class VerifiedSubject:
    issuer: str
    subject: str
    tenant_id: str


@dataclass(frozen=True)
class _Config:
    issuer: str
    audience: str
    jwks_url: str
    tenant_claim: str
    allowed_hosts: frozenset[str]


_JWKS_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_CACHE_LOCK = threading.Lock()
_JWKS_CACHE_TTL = 300
_MAX_JWKS_BYTES = 65536
_MAX_JWKS_KEYS = 32
_MAX_TOKEN_BYTES = 8192


def _https_host(url: str, allowed_hosts: frozenset[str]) -> str:
    if not isinstance(url, str) or not url or len(url) > 512:
        raise ApprovalIdentityError("invalid OIDC URL configuration")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ApprovalIdentityError("invalid OIDC URL configuration") from None
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
        or host not in allowed_hosts
    ):
        raise ApprovalIdentityError("OIDC URL is outside the HTTPS host allowlist")
    return host


def _config(environ=None) -> _Config:
    env = os.environ if environ is None else environ
    issuer = env.get("OLA_APPROVAL_OIDC_ISSUER", "").strip()
    audience = env.get("OLA_APPROVAL_OIDC_AUDIENCE", "").strip()
    jwks_url = env.get("OLA_APPROVAL_OIDC_JWKS_URL", "").strip()
    raw_hosts = env.get("OLA_APPROVAL_OIDC_JWKS_HOST_ALLOWLIST", "")
    hosts = frozenset(h.strip().lower().rstrip(".") for h in raw_hosts.split(",") if h.strip())
    tenant_claim = env.get("OLA_APPROVAL_OIDC_TENANT_CLAIM", "ola_tenant_id").strip()

    if not issuer or not audience or not jwks_url or not hosts:
        raise ApprovalIdentityError("OIDC approval identity configuration is incomplete")
    if len(issuer) > 512 or len(audience) > 256 or any(ord(ch) < 32 for ch in issuer + audience):
        raise ApprovalIdentityError("OIDC issuer or audience configuration is invalid")
    for host in hosts:
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", host) or "*" in host:
            raise ApprovalIdentityError("invalid OIDC host allowlist entry")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", tenant_claim):
        raise ApprovalIdentityError("invalid tenant claim name")
    _https_host(issuer, hosts)
    _https_host(jwks_url, hosts)
    return _Config(issuer, audience, jwks_url, tenant_claim, hosts)


def _fetch_jwks(url: str) -> dict:
    """Fetch bounded JSON without redirects; URL is checked against allowlist first."""
    try:
        with httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ApprovalIdentityError("JWKS endpoint did not return HTTP 200")
                declared = response.headers.get("content-length")
                if declared and int(declared) > _MAX_JWKS_BYTES:
                    raise ApprovalIdentityError("JWKS response exceeds size limit")
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > _MAX_JWKS_BYTES:
                        raise ApprovalIdentityError("JWKS response exceeds size limit")
                    chunks.append(chunk)
                payload = json.loads(b"".join(chunks))
    except ApprovalIdentityError:
        raise
    except (httpx.HTTPError, ValueError):
        raise ApprovalIdentityError("JWKS fetch or parse failed") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list) or len(payload["keys"]) > _MAX_JWKS_KEYS:
        raise ApprovalIdentityError("JWKS document shape is invalid")
    return payload


def _get_jwks(url: str, *, force_refresh=False) -> dict:
    now = time.monotonic()
    with _JWKS_CACHE_LOCK:
        cached = _JWKS_CACHE.get(url)
        if not force_refresh and cached and now < cached[0]:
            return cached[1]
    payload = _fetch_jwks(url)
    with _JWKS_CACHE_LOCK:
        _JWKS_CACHE[url] = (time.monotonic() + _JWKS_CACHE_TTL, payload)
    return payload


def _key_for_kid(jwks: dict, kid: str):
    matches = [row for row in jwks["keys"] if isinstance(row, dict) and row.get("kid") == kid]
    if len(matches) != 1:
        return None
    row = matches[0]
    if row.get("kty") != "RSA" or row.get("use") not in (None, "sig") or row.get("alg") not in (None, "RS256"):
        return None
    try:
        key = jwt.PyJWK.from_dict(row, algorithm="RS256").key
        if getattr(key, "key_size", 0) < 2048:
            return None
        return key
    except (jwt.PyJWTError, TypeError, ValueError):
        return None


def verify_subject_token(token: str, *, environ=None) -> VerifiedSubject:
    """Verify RS256 OIDC JWT and return only the issuer/subject/tenant binding.

    No approval decision is made here. Callers must authorize the subject for
    the tenant and compare author/reviewer subjects before any approval action.
    """
    config = _config(environ)
    if not isinstance(token, str) or not token or not token.isascii() or len(token) > _MAX_TOKEN_BYTES:
        raise ApprovalIdentityError("invalid approval identity token")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise ApprovalIdentityError("invalid approval identity token") from None
    kid = header.get("kid")
    if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid or len(kid) > 128:
        raise ApprovalIdentityError("unsupported approval identity token header")

    jwks = _get_jwks(config.jwks_url)
    key = _key_for_kid(jwks, kid)
    if key is None:
        # One bounded refresh handles rotation or a stale cache; no retry loop.
        jwks = _get_jwks(config.jwks_url, force_refresh=True)
        key = _key_for_kid(jwks, kid)
    if key is None:
        raise ApprovalIdentityError("signing key not found or ambiguous")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=config.issuer,
            audience=config.audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=0,
        )
    except jwt.PyJWTError:
        raise ApprovalIdentityError("approval identity token verification failed") from None

    subject = claims.get("sub")
    tenant_id = claims.get(config.tenant_claim)
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > 256
        or any(ord(ch) < 32 for ch in subject)
        or not isinstance(tenant_id, str)
        or not tenant_id
        or len(tenant_id) > 128
        or any(ord(ch) < 32 for ch in tenant_id)
    ):
        raise ApprovalIdentityError("required approval identity claims are invalid")
    return VerifiedSubject(config.issuer, subject, tenant_id)
