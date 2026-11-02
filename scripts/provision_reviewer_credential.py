"""Issue one REVIEW_RESULT credential through local runtime administration.

Default CLI mode is read-only. Apply is for the owner's private terminal only:
the secret is displayed once after commit. Inventory IDs are pins, not proof of
the local administrator's identity or of an independent human reviewer.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api_key_crypto import KeyConfigurationError, hash_api_key
from app.models import ApiKey, Tenant
from scripts.provision_additional_tenant_key import _UUID_TEXT, _database_session


def _validate_inventory_inputs(tenant_id, expected_requester_id, expected_active_key_count):
    for value in (tenant_id, expected_requester_id):
        if not isinstance(value, str) or _UUID_TEXT.fullmatch(value) is None:
            raise ValueError("tenant and requester IDs must be UUID text")
    if type(expected_active_key_count) is not int or expected_active_key_count < 1:
        raise ValueError("expected active key count must be a positive integer")


def _inspect_requester_inventory(db, tenant_id, expected_requester_id, expected_active_key_count):
    if db.get(Tenant, tenant_id) is None:
        raise ValueError("existing tenant not found")
    requester = db.get(ApiKey, expected_requester_id)
    if (
        requester is None
        or requester.tenant_id != tenant_id
        or requester.revoked_at is not None
        or requester.access_scope != "OLA_CORE"
    ):
        raise ValueError("requester pin is not an active OLA_CORE credential for this tenant")
    count = db.scalar(select(func.count()).select_from(ApiKey).where(
        ApiKey.tenant_id == tenant_id, ApiKey.revoked_at.is_(None)))
    if count != expected_active_key_count:
        raise ValueError("active key count differs from the expected count")
    return count


def inspect_reviewer_credential(
    tenant_id: str, *, expected_requester_id: str, expected_active_key_count: int = 1,
) -> dict:
    """Check an existing deployment without issuing or returning a credential."""
    _validate_inventory_inputs(tenant_id, expected_requester_id, expected_active_key_count)
    hash_api_key("reviewer-credential-configuration-check")
    with _database_session() as db:
        count = _inspect_requester_inventory(
            db, tenant_id, expected_requester_id, expected_active_key_count)
    return {
        "schema": "ola.reviewer-credential.v1", "status": "DRY_RUN",
        "tenant_id": tenant_id, "requester_credential_id": expected_requester_id,
        "active_key_count": count, "access_scope": "REVIEW_RESULT", "mutations": 0,
        "assurance": "UNKNOWN", "production_eligible": False,
    }


def issue_reviewer_credential(
    tenant_id: str, *, expected_requester_id: str, expected_active_key_count: int = 1,
) -> tuple[str, str, str]:
    """Add one review-only key; concurrent/repeated inventory pins fail closed."""
    _validate_inventory_inputs(tenant_id, expected_requester_id, expected_active_key_count)
    with _database_session(write=True) as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        _inspect_requester_inventory(db, tenant_id, expected_requester_id, expected_active_key_count)
        raw_key = "ola2_" + secrets.token_urlsafe(40)
        credential_id = str(uuid.uuid4())
        db.add(ApiKey(id=credential_id, tenant_id=tenant_id,
                      key_hash=hash_api_key(raw_key), access_scope="REVIEW_RESULT"))
        db.commit()
    return tenant_id, credential_id, raw_key


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--expected-requester-id", required=True)
    parser.add_argument("--expected-active-key-count", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-review-result-access", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.apply and not args.acknowledge_review_result_access:
            raise ValueError("--apply requires --acknowledge-review-result-access")
        if args.apply and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise ValueError("--apply requires interactive stdin and stdout in a private terminal")
        kwargs = {"expected_requester_id": args.expected_requester_id,
                  "expected_active_key_count": args.expected_active_key_count}
        if not args.apply:
            print(json.dumps(inspect_reviewer_credential(args.tenant_id, **kwargs), sort_keys=True))
            return 0
        tenant_id, credential_id, raw_key = issue_reviewer_credential(args.tenant_id, **kwargs)
    except (ValueError, KeyConfigurationError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError) as exc:
        print("BLOCKED: local operation failed (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2
    print("OLA_REVIEWER_CREDENTIAL_CREATED")
    print("TENANT_ID: " + tenant_id)
    print("CREDENTIAL_ID: " + credential_id)
    print("ACCESS_SCOPE: REVIEW_RESULT")
    print("ASSURANCE: UNKNOWN")
    print("PRODUCTION_ELIGIBLE: false")
    print("X_API_KEY_ONCE: " + raw_key)
    print("Different credentials do not prove different people. Distribute privately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
