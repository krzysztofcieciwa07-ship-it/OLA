"""Application context plus opaque evidence for PostgreSQL tenant authorization.

The tenant id is an application hint only. PostgreSQL authorization is established
from a database-verifiable API key, worker claim, or Checkout Session binding.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import re

_tenant_id = ContextVar("ola_tenant_id", default=None)
_worker_mode = ContextVar("ola_worker_mode", default=False)
_database_auth_context = ContextVar("ola_database_auth_context", default=None)

_API_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


def current_tenant_id():
    return _tenant_id.get()


def current_database_auth_context():
    """Return the immutable evidence tuple consumed by SQLAlchemy's begin hook."""
    return _database_auth_context.get()


def set_database_auth_context(kind, *values):
    """Set one typed authentication proof; never accepts a caller tenant id."""
    if kind is None:
        if values:
            raise ValueError("clearing database auth context takes no values")
        return _database_auth_context.set(None)
    if kind == "api_key":
        if len(values) != 1 or not isinstance(values[0], str) or not _API_KEY_RE.fullmatch(values[0]):
            raise ValueError("API-key context requires a 64-character lowercase hex fingerprint")
    elif kind == "worker_claim":
        if (len(values) != 3 or not isinstance(values[0], str) or not values[0]
                or len(values[0]) > 128 or not values[0].isascii()
                or not isinstance(values[1], str) or not _TOKEN_RE.fullmatch(values[1])
                or type(values[2]) is not int or not 60 <= values[2] <= 86400):
            raise ValueError("worker context requires job id, claim token, and bounded lease")
    elif kind == "checkout":
        if (len(values) != 2 or not isinstance(values[0], str) or not values[0]
                or len(values[0]) > 128 or not values[0].isascii()
                or not isinstance(values[1], str) or not values[1].startswith("cs_test_")
                or len(values[1]) > 255 or not values[1].isascii()):
            raise ValueError("checkout context requires an OLA order id and sandbox session id")
    else:
        raise ValueError("unsupported database authentication evidence kind")
    return _database_auth_context.set((kind, *values))


def set_api_key_context(key_fingerprint):
    return set_database_auth_context("api_key", key_fingerprint)


def set_worker_claim_context(job_id, claim_token, stale_after_seconds=900):
    return set_database_auth_context("worker_claim", job_id, claim_token, stale_after_seconds)


def set_checkout_context(order_id, session_id):
    return set_database_auth_context("checkout", order_id, session_id)


def reset_database_auth_context(token):
    _database_auth_context.reset(token)


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
