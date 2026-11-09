"""Ed25519 request authentication and durable replay protection for agent calls."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal
from .models import SecureBridgeNonce


BRIDGE_PATH = "/api/v1/secure-bridge/invoke"
BRIDGE_METHOD = "POST"
BRIDGE_DOMAIN = "OLA-SECURE-BRIDGE-V1"
MAX_BODY_BYTES = 64 * 1024
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TIMESTAMP_RE = re.compile(r"^[1-9][0-9]{9}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-fA-F]{128}$")
_AGENT_ID_RE = re.compile(r"^agent-[0-9]{3}$")


class SecureBridgeUnavailable(RuntimeError):
    """The bridge is disabled or its trust configuration is invalid."""


class SecureBridgeUnauthorized(ValueError):
    """The request has no valid, currently trusted signing identity."""


class SecureBridgeNonceReplay(ValueError):
    """The key has already used this nonce inside the replay window."""


class NonceStoreUnavailable(RuntimeError):
    """The persistent nonce store could not provide replay protection."""


@dataclass(frozen=True)
class BridgePrincipal:
    key_id: str
    tenant_id: str
    agent_id: str
    scopes: frozenset[str]


def build_signing_message(
    *, key_id: str, timestamp: str, nonce: str,
    method: str, path: str, audience: str, body: bytes,
) -> bytes:
    """Build the exact versioned Ed25519 signing input from raw HTTP bytes."""
    if not isinstance(body, bytes):
        raise ValueError("request body must be exact bytes")
    fields = (key_id, timestamp, nonce, method, path, audience)
    if any(not isinstance(value, str) or not value or "\n" in value or "\r" in value for value in fields):
        raise ValueError("signing fields must be non-empty single-line strings")
    body_digest = hashlib.sha256(body).hexdigest()
    return "\n".join((
        BRIDGE_DOMAIN, key_id, timestamp, nonce,
        method.upper(), path, audience, body_digest,
    )).encode("utf-8")


def _clock_skew_seconds(env: Mapping[str, str]) -> int:
    raw = env.get("OLA_SECURE_BRIDGE_CLOCK_SKEW_SECONDS", "60")
    if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]{0,2}", raw):
        raise SecureBridgeUnavailable("secure bridge clock-skew configuration is invalid")
    value = int(raw)
    if value > 300:
        raise SecureBridgeUnavailable("secure bridge clock-skew configuration is outside policy")
    return value


def _load_trusted_keys(env: Mapping[str, str]) -> dict[str, tuple[BridgePrincipal, bytes]]:
    raw = env.get("OLA_SECURE_BRIDGE_KEYS_JSON", "")
    if not raw.strip():
        raise SecureBridgeUnavailable("secure bridge trusted keys are not configured")
    try:
        configured = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SecureBridgeUnavailable("secure bridge key registry is invalid") from exc
    if not isinstance(configured, list) or not configured or len(configured) > 1024:
        raise SecureBridgeUnavailable("secure bridge key registry must be a non-empty bounded list")

    result: dict[str, tuple[BridgePrincipal, bytes]] = {}
    for item in configured:
        if not isinstance(item, dict):
            raise SecureBridgeUnavailable("secure bridge key registry entry is invalid")
        key_id = item.get("key_id")
        tenant_id = item.get("tenant_id")
        agent_id = item.get("agent_id")
        encoded_key = item.get("public_key_b64")
        scopes = item.get("scopes")
        if (
            not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None
            or not isinstance(tenant_id, str) or not tenant_id.strip() or len(tenant_id) > 128
            or not isinstance(agent_id, str) or _AGENT_ID_RE.fullmatch(agent_id) is None
            or not isinstance(encoded_key, str) or not encoded_key
            or not isinstance(scopes, list) or not scopes
            or not all(isinstance(scope, str) and re.fullmatch(r"[a-z][a-z0-9:_-]{0,63}", scope) for scope in scopes)
            or len(set(scopes)) != len(scopes)
        ):
            raise SecureBridgeUnavailable("secure bridge key registry entry is malformed")
        if key_id in result:
            raise SecureBridgeUnavailable("secure bridge key registry contains duplicate key IDs")
        try:
            public_bytes = base64.b64decode(encoded_key, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise SecureBridgeUnavailable("secure bridge public key encoding is invalid") from exc
        if len(public_bytes) != 32:
            raise SecureBridgeUnavailable("secure bridge Ed25519 public keys must be 32 bytes")
        result[key_id] = (
            BridgePrincipal(
                key_id=key_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                scopes=frozenset(scopes),
            ),
            public_bytes,
        )
    return result


def _revoked_key_ids(env: Mapping[str, str]) -> frozenset[str]:
    raw = env.get("OLA_SECURE_BRIDGE_REVOKED_KEY_IDS", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if any(_KEY_ID_RE.fullmatch(item) is None for item in values):
        raise SecureBridgeUnavailable("secure bridge revocation configuration is invalid")
    return frozenset(values)


def authenticate_signed_request(
    *,
    key_id: str | None,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    method: str,
    path: str,
    body: bytes,
    now: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[BridgePrincipal, int]:
    """Validate signature and trust state without consuming the nonce.

    Unauthenticated failures never mutate agent quarantine state: a supplied
    key ID is not proof of the caller's identity.
    """
    env = os.environ if environ is None else environ
    audience = env.get("OLA_SECURE_BRIDGE_AUDIENCE", "").strip()
    if not audience or len(audience) > 255 or "\n" in audience or "\r" in audience:
        raise SecureBridgeUnavailable("secure bridge audience is not configured")
    skew = _clock_skew_seconds(env)
    if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
        raise SecureBridgeUnauthorized("request body is invalid")
    if (
        not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None
        or not isinstance(timestamp, str) or _TIMESTAMP_RE.fullmatch(timestamp) is None
        or not isinstance(nonce, str) or _NONCE_RE.fullmatch(nonce) is None
        or not isinstance(signature, str) or _SIGNATURE_RE.fullmatch(signature) is None
        or method.upper() != BRIDGE_METHOD
        or path != BRIDGE_PATH
    ):
        raise SecureBridgeUnauthorized("request authentication failed")

    timestamp_value = int(timestamp)
    current_time = int(time.time()) if now is None else int(now)
    if abs(current_time - timestamp_value) > skew:
        raise SecureBridgeUnauthorized("request authentication failed")

    trusted_keys = _load_trusted_keys(env)
    if key_id in _revoked_key_ids(env):
        raise SecureBridgeUnauthorized("request authentication failed")
    entry = trusted_keys.get(key_id)
    if entry is None:
        raise SecureBridgeUnauthorized("request authentication failed")
    principal, public_bytes = entry

    message = build_signing_message(
        key_id=key_id, timestamp=timestamp, nonce=nonce,
        method=method, path=path, audience=audience, body=body,
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            bytes.fromhex(signature), message,
        )
    except (InvalidSignature, ValueError):
        raise SecureBridgeUnauthorized("request authentication failed") from None
    return principal, skew


def consume_nonce(
    *, key_id: str, nonce: str, retention_seconds: int, now: int | None = None,
) -> None:
    """Atomically reserve a key-scoped nonce using a database unique constraint."""
    if retention_seconds < 60 or retention_seconds > 900:
        raise ValueError("nonce retention must be between 60 and 900 seconds")
    current_time = int(time.time()) if now is None else int(now)
    nonce_hash = hashlib.sha256(nonce.encode("ascii")).hexdigest()

    db = SessionLocal()
    try:
        # SQLite's local single-process runtime has no separate SQL role.
        # Keep its small development ledger bounded here; PostgreSQL cleanup
        # is deliberately delegated to the separate maintenance principal.
        if db.get_bind().dialect.name == "sqlite":
            db.execute(
                delete(SecureBridgeNonce).where(
                    SecureBridgeNonce.expires_at <= current_time
                )
            )
        db.add(SecureBridgeNonce(
            key_id=key_id,
            nonce_hash=nonce_hash,
            created_at=current_time,
            expires_at=current_time + retention_seconds,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise SecureBridgeNonceReplay("request nonce already used") from None
    except Exception as exc:
        db.rollback()
        raise NonceStoreUnavailable() from exc
    finally:
        db.close()



def prune_expired_nonces(target_engine, *, now: int | None = None) -> int:
    """Delete expired replay records using a separate maintenance/migration principal.

    The online API runtime intentionally has INSERT-only access to the nonce
    table; it cannot erase replay history. Run this helper from a scheduled
    maintenance process with the database migration/maintenance credentials.
    """
    if target_engine.dialect.name != "postgresql":
        raise RuntimeError("nonce maintenance requires PostgreSQL")
    current_time = int(time.time()) if now is None else int(now)
    with target_engine.begin() as conn:
        result = conn.execute(
            delete(SecureBridgeNonce).where(SecureBridgeNonce.expires_at <= current_time)
        )
    return max(0, int(result.rowcount or 0))
