"""Transaction-local PostgreSQL RLS context for authenticated tenant requests."""
from contextlib import contextmanager
from contextvars import ContextVar

_tenant_id = ContextVar("ola_tenant_id", default=None)
_worker_mode = ContextVar("ola_worker_mode", default=False)


def current_tenant_id():
    return _tenant_id.get()


def worker_mode_enabled():
    return _worker_mode.get() is True


def set_worker_mode(enabled):
    if not isinstance(enabled, bool):
        raise ValueError("worker mode must be a boolean")
    return _worker_mode.set(enabled)


def set_current_tenant_id(tenant_id):
    if tenant_id is not None and (not isinstance(tenant_id, str) or not tenant_id.strip()):
        raise ValueError("tenant context must be a nonempty string or None")
    return _tenant_id.set(tenant_id)


def reset_current_tenant_id(token):
    _tenant_id.reset(token)


@contextmanager
def tenant_scope(tenant_id):
    token = set_current_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_current_tenant_id(token)


@contextmanager
def worker_scope():
    worker_token = _worker_mode.set(True)
    tenant_token = set_current_tenant_id(None)
    try:
        yield
    finally:
        reset_current_tenant_id(tenant_token)
        _worker_mode.reset(worker_token)
