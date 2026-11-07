"""Opaque, encrypted, server-side sessions for OLA human operators.

The browser holds only a random bearer session token. All session payloads,
including short-lived OIDC state/nonce/PKCE verifier values, are encrypted
before persistence. OAuth access/refresh/ID tokens and client secrets are
never accepted in session payloads.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from starlette.types import ASGIApp, Receive, Scope, Send

from app.database import SessionLocal
from app.models import HumanSession


AUTH_SESSION_KEY = "__ola_human_auth__"
FORBIDDEN_SESSION_KEYS = frozenset({
    "access_token", "refresh_token", "id_token", "client_secret",
    "api_key", "x_api_key", "authorization", "bearer_token",
})
DEFAULT_COOKIE_NAME = "ola_human_session"
DEFAULT_TTL_SECONDS = 8 * 60 * 60
MAX_SESSION_PAYLOAD_BYTES = 16 * 1024


class HumanSessionUnavailable(RuntimeError):
    """Raised when session encryption or persistence is not safely available."""


class HumanSessionRejected(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HumanSessionContext:
    tenant_id: str
    principal_ref: str
    auth_time: int | None
    mfa_verified: bool
    expires_at: int


class _TrackedSession(dict):
    def __init__(self, data: dict[str, Any] | None = None):
        super().__init__(data or {})
        self.modified = False
        self.rotate_on_save = False
        self.expire_cookie = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.modified = True

    def __delitem__(self, key):
        super().__delitem__(key)
        self.modified = True

    def clear(self):
        if self:
            super().clear()
            self.modified = True

    def pop(self, key, *default):
        if key in self:
            self.modified = True
        return super().pop(key, *default)

    def popitem(self):
        value = super().popitem()
        self.modified = True
        return value

    def update(self, *args, **kwargs):
        values = dict(*args, **kwargs)
        if values:
            super().update(values)
            self.modified = True

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self.modified = True
        return super().setdefault(key, default)

    def rotate(self):
        self.rotate_on_save = True
        self.modified = True

    def clear_cookie(self):
        self.clear()
        self.expire_cookie = True
        self.modified = True


def _fernet() -> Fernet:
    raw_key = os.environ.get("OLA_HUMAN_SESSION_ENCRYPTION_KEY")
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise HumanSessionUnavailable(
            "OLA_HUMAN_SESSION_ENCRYPTION_KEY is required for Human Identity sessions"
        )
    try:
        return Fernet(raw_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise HumanSessionUnavailable(
            "Human Identity session encryption key is invalid"
        ) from exc


def _session_hash(raw_token: str) -> str:
    if not isinstance(raw_token, str) or len(raw_token) < 32 or len(raw_token) > 256:
        raise HumanSessionRejected(401, "invalid Human Identity session token")
    return hashlib.sha256(raw_token.encode("ascii", errors="strict")).hexdigest()


def _validate_session_payload(session_data: dict[str, Any]) -> bytes:
    if not isinstance(session_data, dict):
        raise HumanSessionUnavailable("Human Identity session payload must be an object")

    def inspect_value(value: Any, depth: int = 0):
        if depth > 8:
            raise HumanSessionUnavailable("Human Identity session payload is too deeply nested")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise HumanSessionUnavailable("Human Identity session keys must be strings")
                if key.casefold() in FORBIDDEN_SESSION_KEYS:
                    raise HumanSessionUnavailable("OAuth tokens and API credentials cannot be stored in a Human Identity session")
                inspect_value(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                inspect_value(child, depth + 1)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise HumanSessionUnavailable("Human Identity session payload contains a non-JSON value")

    inspect_value(session_data)
    try:
        encoded = json.dumps(
            session_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HumanSessionUnavailable("Human Identity session payload is not valid JSON") from exc
    if len(encoded) > MAX_SESSION_PAYLOAD_BYTES:
        raise HumanSessionUnavailable("Human Identity session payload exceeds 16 KiB")
    return encoded


def _encrypt_session_payload(session_data: dict[str, Any]) -> str:
    encoded = _validate_session_payload(session_data)
    return _fernet().encrypt(encoded).decode("ascii")


def _decrypt_session_payload(encrypted: str) -> dict[str, Any]:
    try:
        decoded = _fernet().decrypt(encrypted.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HumanSessionUnavailable("Human Identity session payload cannot be decrypted") from exc
    if not isinstance(payload, dict):
        raise HumanSessionUnavailable("Human Identity session payload is invalid")
    _validate_session_payload(payload)
    return payload


def _new_raw_token() -> str:
    return secrets.token_urlsafe(32)


def _write_session(
    raw_token: str,
    *,
    tenant_id: str | None,
    principal_ref: str | None,
    session_data: dict[str, Any],
    auth_time: int | None,
    mfa_verified: bool,
    ttl_seconds: int,
) -> HumanSession:
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 24 * 60 * 60:
        raise HumanSessionUnavailable("Human Identity session TTL must be between 60 and 86400 seconds")
    token_hash = _session_hash(raw_token)
    encrypted = _encrypt_session_payload(session_data)
    now = int(time.time())
    with SessionLocal() as db:
        existing = db.scalar(
            select(HumanSession)
            .where(HumanSession.session_hash == token_hash)
            .with_for_update()
        )
        if existing is not None:
            if existing.revoked_at is not None or existing.expires_at <= now:
                raise HumanSessionRejected(401, "Human Identity session is revoked or expired")
            existing.tenant_id = tenant_id
            existing.principal_ref = principal_ref
            existing.session_data_encrypted = encrypted
            existing.auth_time = auth_time
            existing.mfa_verified = bool(mfa_verified)
            existing.updated_at = now
            existing.expires_at = now + ttl_seconds
            db.commit()
            db.refresh(existing)
            return existing

        row = HumanSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            principal_ref=principal_ref,
            session_hash=token_hash,
            session_data_encrypted=encrypted,
            auth_time=auth_time,
            mfa_verified=bool(mfa_verified),
            created_at=now,
            updated_at=now,
            expires_at=now + ttl_seconds,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def _load_session(raw_token: str) -> tuple[HumanSession | None, dict[str, Any]]:
    token_hash = _session_hash(raw_token)
    now = int(time.time())
    with SessionLocal() as db:
        row = db.scalar(select(HumanSession).where(HumanSession.session_hash == token_hash))
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            return None, {}
        encrypted = row.session_data_encrypted
    return row, _decrypt_session_payload(encrypted)


def _revoke_token(raw_token: str) -> None:
    try:
        token_hash = _session_hash(raw_token)
    except (HumanSessionRejected, UnicodeEncodeError):
        return
    now = int(time.time())
    with SessionLocal() as db:
        row = db.scalar(
            select(HumanSession)
            .where(HumanSession.session_hash == token_hash)
            .with_for_update()
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = now
            row.updated_at = now
            db.commit()


def create_human_session(
    *,
    tenant_id: str | None,
    principal_ref: str | None,
    session_data: dict[str, Any],
    auth_time: int | None,
    mfa_verified: bool,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Create a server-side session and return its one-time browser token."""
    raw_token = _new_raw_token()
    row = _write_session(
        raw_token,
        tenant_id=tenant_id,
        principal_ref=principal_ref,
        session_data=session_data,
        auth_time=auth_time,
        mfa_verified=mfa_verified,
        ttl_seconds=ttl_seconds,
    )
    return {
        "session_token": raw_token,
        "session_id": row.id,
        "expires_at": row.expires_at,
    }


def resolve_human_session(raw_token: str | None) -> HumanSessionContext | None:
    """Return a verified active login context; never returns OIDC tokens/claims."""
    if not raw_token:
        return None
    try:
        row, payload = _load_session(raw_token)
    except (HumanSessionRejected, HumanSessionUnavailable, UnicodeEncodeError):
        return None
    if row is None:
        return None
    auth = payload.get(AUTH_SESSION_KEY)
    if not isinstance(auth, dict):
        return None
    tenant_id = auth.get("tenant_id")
    principal_ref = auth.get("principal_ref")
    auth_time = auth.get("auth_time")
    mfa_verified = auth.get("mfa_verified")
    if not isinstance(tenant_id, str) or not tenant_id:
        return None
    if not isinstance(principal_ref, str) or not principal_ref:
        return None
    if auth_time is not None and type(auth_time) is not int:
        return None
    if type(mfa_verified) is not bool:
        return None
    return HumanSessionContext(
        tenant_id=tenant_id,
        principal_ref=principal_ref,
        auth_time=auth_time,
        mfa_verified=mfa_verified,
        expires_at=row.expires_at,
    )


def establish_human_session(
    request,
    *,
    tenant_id: str,
    principal_ref: str,
    auth_time: int | None,
    mfa_verified: bool,
) -> None:
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HumanSessionRejected(400, "tenant_id is required")
    if not isinstance(principal_ref, str) or not principal_ref:
        raise HumanSessionRejected(400, "principal_ref is required")
    if auth_time is not None and type(auth_time) is not int:
        raise HumanSessionRejected(400, "auth_time must be a Unix timestamp")
    if type(mfa_verified) is not bool:
        raise HumanSessionRejected(400, "mfa_verified must be boolean")
    session = request.scope.get("session")
    if not isinstance(session, _TrackedSession):
        raise HumanSessionUnavailable("server-side Human Identity middleware is not installed")
    session.clear()
    session[AUTH_SESSION_KEY] = {
        "tenant_id": tenant_id,
        "principal_ref": principal_ref,
        "auth_time": auth_time,
        "mfa_verified": mfa_verified,
        "csrf_token": secrets.token_urlsafe(32),
    }
    session.rotate()


def require_human_session(request, *, tenant_id: str | None = None) -> HumanSessionContext:
    raw_token = request.scope.get("human_session_token")
    context = resolve_human_session(raw_token)
    if context is None:
        raise HumanSessionRejected(401, "authenticated Human Identity session is required")
    if tenant_id is not None and context.tenant_id != tenant_id:
        raise HumanSessionRejected(403, "Human Identity session belongs to a different tenant")
    return context


def revoke_human_session(request) -> None:
    raw_token = request.scope.get("human_session_token")
    if raw_token:
        _revoke_token(raw_token)
    session = request.scope.get("session")
    if isinstance(session, _TrackedSession):
        session.clear_cookie()


def _cookie_token(scope, cookie_name: str) -> str | None:
    cookie_header = next(
        (value.decode("latin-1") for name, value in scope.get("headers", []) if name.lower() == b"cookie"),
        "",
    )
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return None
    morsel = cookie.get(cookie_name)
    return morsel.value if morsel is not None else None


def _set_cookie_header(
    cookie_name: str,
    token: str,
    *,
    max_age: int,
    path: str,
    secure: bool,
) -> bytes:
    cookie = SimpleCookie()
    cookie[cookie_name] = token
    cookie[cookie_name]["path"] = path
    cookie[cookie_name]["max-age"] = str(max_age)
    cookie[cookie_name]["httponly"] = True
    cookie[cookie_name]["samesite"] = "lax"
    if secure:
        cookie[cookie_name]["secure"] = True
    return (b"set-cookie", cookie.output(header="").strip().encode("latin-1"))


def _expired_cookie_header(cookie_name: str, *, path: str, secure: bool) -> bytes:
    cookie = SimpleCookie()
    cookie[cookie_name] = ""
    cookie[cookie_name]["path"] = path
    cookie[cookie_name]["max-age"] = "0"
    cookie[cookie_name]["httponly"] = True
    cookie[cookie_name]["samesite"] = "lax"
    cookie[cookie_name]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    if secure:
        cookie[cookie_name]["secure"] = True
    return (b"set-cookie", cookie.output(header="").strip().encode("latin-1"))


class ServerSideSessionMiddleware:
    """ASGI session middleware using an opaque cookie and encrypted database payload."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        cookie_name: str = DEFAULT_COOKIE_NAME,
        secure_cookie: bool = True,
        cookie_path: str = "/",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        if not cookie_name or any(char in cookie_name for char in "=; ,"):
            raise ValueError("invalid Human Identity session cookie name")
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 24 * 60 * 60:
            raise ValueError("Human Identity session TTL must be between 60 and 86400 seconds")
        self.app = app
        self.cookie_name = cookie_name
        self.secure_cookie = secure_cookie
        self.cookie_path = cookie_path
        self.ttl_seconds = ttl_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_token = _cookie_token(scope, self.cookie_name)
        row = None
        payload: dict[str, Any] = {}
        invalid_cookie = False
        if raw_token:
            try:
                row, payload = _load_session(raw_token)
            except (HumanSessionRejected, HumanSessionUnavailable, UnicodeEncodeError):
                invalid_cookie = True
            if row is None:
                invalid_cookie = True

        session = _TrackedSession(payload)
        scope["session"] = session
        scope["human_session_token"] = raw_token if row is not None else None
        scope["human_session_record_id"] = row.id if row is not None else None

        replacement_response = False

        async def send_with_session(message):
            nonlocal replacement_response
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if session.expire_cookie:
                    if raw_token:
                        _revoke_token(raw_token)
                    headers.append(_expired_cookie_header(
                        self.cookie_name, path=self.cookie_path, secure=self.secure_cookie,
                    ))
                elif session.modified:
                    try:
                        if session.rotate_on_save or row is None:
                            if raw_token and session.rotate_on_save and row is not None:
                                _revoke_token(raw_token)
                            save_token = _new_raw_token()
                        else:
                            save_token = raw_token
                        auth = session.get(AUTH_SESSION_KEY)
                        if not isinstance(auth, dict):
                            auth = {}
                        tenant_id = auth.get("tenant_id")
                        principal_ref = auth.get("principal_ref")
                        auth_time = auth.get("auth_time")
                        mfa_verified = auth.get("mfa_verified", False)
                        _write_session(
                            save_token,
                            tenant_id=tenant_id if isinstance(tenant_id, str) else None,
                            principal_ref=principal_ref if isinstance(principal_ref, str) else None,
                            session_data=dict(session),
                            auth_time=auth_time if type(auth_time) is int else None,
                            mfa_verified=bool(mfa_verified),
                            ttl_seconds=self.ttl_seconds,
                        )
                        scope["human_session_token"] = save_token
                        headers.append(_set_cookie_header(
                            self.cookie_name,
                            save_token,
                            max_age=self.ttl_seconds,
                            path=self.cookie_path,
                            secure=self.secure_cookie,
                        ))
                    except (HumanSessionUnavailable, HumanSessionRejected):
                        replacement_response = True
                        body = b'{"detail":"Human Identity session storage is unavailable"}'
                        await send({
                            "type": "http.response.start",
                            "status": 503,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("ascii")),
                                _expired_cookie_header(
                                    self.cookie_name, path=self.cookie_path, secure=self.secure_cookie,
                                ),
                            ],
                        })
                        return
                elif invalid_cookie:
                    headers.append(_expired_cookie_header(
                        self.cookie_name, path=self.cookie_path, secure=self.secure_cookie,
                    ))
                message["headers"] = headers
            elif replacement_response and message["type"] == "http.response.body":
                if message.get("more_body", False):
                    return
                message = {
                    "type": "http.response.body",
                    "body": b'{"detail":"Human Identity session storage is unavailable"}',
                    "more_body": False,
                }
            await send(message)

        await self.app(scope, receive, send_with_session)
