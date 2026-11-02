"""Request-local Core authority, rechecked inside Evidence writer transactions.

The mutable holder is per ASGI request: anyio copies its ContextVar into sync
endpoint workers while retaining the holder reference. No raw key is retained.
Independent internal/webhook calls do not acquire a Core authority implicitly.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import HTTPException

from .models import ApiKey


@dataclass(frozen=True)
class CoreAuthority:
    tenant_id: str
    credential_id: str
    key_hash: str


@dataclass
class RequestAuthority:
    core: CoreAuthority | None = None
    closed: bool = False


_request_authority: ContextVar[RequestAuthority | None] = ContextVar(
    "ola_request_authority", default=None,
)


class RequestAuthorityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        holder = RequestAuthority()
        token = _request_authority.set(holder)
        try:
            await self.app(scope, receive, send)
        finally:
            # A copied context in detached work must not retain live authority
            # after this request has finished. Reset also isolates later calls.
            holder.closed = True
            _request_authority.reset(token)


def bind_core_authority(tenant_id, credential_id, key_hash):
    holder = _request_authority.get()
    if holder is not None:
        if holder.closed:
            raise HTTPException(status_code=401, detail="invalid API key")
        holder.core = CoreAuthority(tenant_id, credential_id, key_hash)


def assert_core_write_authorized(db, tenant_id):
    """Called only after BEGIN IMMEDIATE, in the transaction doing the write."""
    holder = _request_authority.get()
    if holder is None or holder.core is None:
        return
    if holder.closed:
        raise HTTPException(status_code=401, detail="invalid API key")
    authority = holder.core
    key = db.get(ApiKey, authority.credential_id, populate_existing=True)
    if (
        key is None
        or key.revoked_at is not None
        or key.tenant_id != authority.tenant_id
        or key.key_hash != authority.key_hash
        or tenant_id != authority.tenant_id
    ):
        raise HTTPException(status_code=401, detail="invalid API key")
    if key.access_scope != "OLA_CORE":
        raise HTTPException(status_code=403, detail="OLA_CORE credential required")

