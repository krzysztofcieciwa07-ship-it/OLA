"""Issue an additional FULL_TENANT_ACCESS credential through local administration.

Default CLI mode only inspects an existing tenant. Writing requires explicit
acknowledgement and a private interactive terminal. No API, role, human identity,
or production permission is added: different credentials do not prove different
people. Use this only in the configured local runtime, never a CI/log collector.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.api_key_crypto import KeyConfigurationError, hash_api_key
from app.database import DB_PATH
from app.models import ApiKey, Tenant


_UUID_TEXT = re.compile(
    r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\Z"
)


def _validate_inputs(tenant_id, expected_requester_id, expected_key_count):
    for value in (tenant_id, expected_requester_id):
        if not isinstance(value, str) or _UUID_TEXT.fullmatch(value) is None:
            raise ValueError("tenant and requester IDs must be UUID text")
    if type(expected_key_count) is not int or expected_key_count < 1:
        raise ValueError("expected key count must be a positive integer")


def _assert_existing_database():
    path = Path(DB_PATH).resolve()
    if not path.is_file():
        raise ValueError("configured database must already exist as a file")
    return path


@contextmanager
def _database_session(*, write=False):
    # The existence check alone has a check/open race. SQLite's URI mode is
    # authoritative: ro and rw both refuse a vanished file; neither creates it.
    path = _assert_existing_database()
    uri = path.as_uri() + ("?mode=rw" if write else "?mode=ro")
    operation_engine = create_engine(
        "sqlite://", poolclass=NullPool,
        creator=lambda: sqlite3.connect(uri, uri=True, timeout=5, check_same_thread=False),
    )
    try:
        with Session(bind=operation_engine, autocommit=False, autoflush=False) as db:
            yield db
    finally:
        operation_engine.dispose()


def _inspect_inventory(db, tenant_id, expected_requester_id, expected_key_count):
    # Query the exact supplied text: persisted IDs also support 32-hex UUIDs.
    if db.get(Tenant, tenant_id) is None:
        raise ValueError("existing tenant not found")
    requester = db.get(ApiKey, expected_requester_id)
    if requester is None or requester.tenant_id != tenant_id:
        raise ValueError("expected requester does not belong to the tenant")
    count = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == tenant_id))
    if count != expected_key_count:
        raise ValueError("existing key count differs from the expected count")
    return count


def inspect_existing_tenant(tenant_id: str, *, expected_requester_id: str,
                            expected_key_count: int = 1) -> dict:
    """Inspect deployment readiness without issuing or returning credentials."""
    _validate_inputs(tenant_id, expected_requester_id, expected_key_count)
    hash_api_key("additional-tenant-credential-configuration-check")
    with _database_session() as db:
        count = _inspect_inventory(db, tenant_id, expected_requester_id, expected_key_count)
    return {
        "schema": "ola.additional-tenant-credential.v1",
        "status": "DRY_RUN", "tenant_id": tenant_id,
        "requester_credential_id": expected_requester_id,
        "existing_key_count": count, "mutations": 0,
        "access_scope": "FULL_TENANT_ACCESS", "assurance": "UNKNOWN",
        "production_eligible": False,
    }


def issue_existing_tenant_key(tenant_id: str, *, expected_requester_id: str,
                              expected_key_count: int = 1) -> tuple[str, str, str]:
    """Add exactly one credential, preserving every existing row and identity.

    Local administrative callers must distribute the returned secret privately.
    The count pin is checked under SQLite's writer reservation, so repeated or
    concurrent issuance with the same inventory cannot silently add more keys.
    """
    _validate_inputs(tenant_id, expected_requester_id, expected_key_count)
    with _database_session(write=True) as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        _inspect_inventory(db, tenant_id, expected_requester_id, expected_key_count)
        raw_key = "ola2_" + secrets.token_urlsafe(40)
        key_hash = hash_api_key(raw_key)  # missing deployment pepper blocks before any INSERT
        credential_id = str(uuid.uuid4())
        db.add(ApiKey(id=credential_id, tenant_id=tenant_id, key_hash=key_hash))
        db.commit()
    return tenant_id, credential_id, raw_key


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--expected-requester-id", required=True)
    parser.add_argument("--expected-key-count", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-full-tenant-access", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.apply and not args.acknowledge_full_tenant_access:
            raise ValueError("--apply requires --acknowledge-full-tenant-access")
        if args.apply and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise ValueError("--apply requires interactive stdin and stdout in a private terminal")
        _assert_existing_database()
        kwargs = {"expected_requester_id": args.expected_requester_id,
                  "expected_key_count": args.expected_key_count}
        if not args.apply:
            print(json.dumps(inspect_existing_tenant(args.tenant_id, **kwargs), sort_keys=True))
            return 0
        tenant_id, credential_id, raw_key = issue_existing_tenant_key(args.tenant_id, **kwargs)
    except (ValueError, KeyConfigurationError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError) as exc:
        # Database exceptions may include SQL parameters, paths, and credentials.
        print("BLOCKED: local operation failed (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2
    print("OLA_ADDITIONAL_TENANT_KEY_CREATED")
    print("TENANT_ID: " + tenant_id)
    print("CREDENTIAL_ID: " + credential_id)
    print("ACCESS_SCOPE: FULL_TENANT_ACCESS")
    print("ASSURANCE: UNKNOWN")
    print("PRODUCTION_ELIGIBLE: false")
    print("X_API_KEY_ONCE: " + raw_key)
    print("Different credentials do not prove different people. Distribute privately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
