import hashlib
import uuid

import pytest
from fastapi import HTTPException

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.main import identity_from_key
from app.models import ApiKey, Tenant


def test_hash_is_keyed_and_not_raw_sha256(monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "test-only-secret-0123456789abcdef-abcdefgh")
    result = api_key_fingerprint("abc")
    assert len(result) == 64
    assert result != hashlib.sha256(b"abc").hexdigest()
    assert result == hashlib.scrypt(b"abc", salt=b"test-only-secret-0123456789abcdef-abcdefgh",
                                   n=1 << 14, r=8, p=1, maxmem=64 * 1024 * 1024,
                                   dklen=32).hex()


def test_pepper_required_fail_closed(monkeypatch):
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        api_key_fingerprint("key")


def test_pepper_change_invalidates_old_fingerprint(monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "test-only-secret-0123456789abcdef-abcdefgh")
    first = api_key_fingerprint("test-key")
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "another-test-secret-0123456789abcdef-abcdefgh")
    assert api_key_fingerprint("test-key") != first


def test_unkeyed_legacy_key_is_not_accepted(monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "test-only-secret-0123456789abcdef-abcdefgh")
    legacy_key = f"old-key-{uuid.uuid4()}"
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="legacy-rejection"))
        db.commit()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=hashlib.sha256(legacy_key.encode()).hexdigest()))
        db.commit()
    with pytest.raises(HTTPException) as exc:
        identity_from_key(legacy_key)
    assert exc.value.status_code == 401


def test_missing_pepper_rejects_api_auth_even_if_db_has_key(monkeypatch):
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    with pytest.raises(HTTPException) as exc:
        identity_from_key("any-key")
    assert exc.value.status_code == 503
