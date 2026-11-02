"""Revoke one pinned tenant credential through local administration.

Default CLI mode only inspects. Apply preserves the credential row and commits
its revoked_at and an append-only credential.revoked event atomically. Runtime
filesystem/database access is the administrative boundary; requester ID is an
inventory pin and is not authentication of a person.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import ApiKey, EvidenceRecord
from app.hashchain import GENESIS_HASH, canonical_json, compute_record_hash, verify_chain
from scripts.provision_additional_tenant_key import _UUID_TEXT, _database_session
from scripts.provision_reviewer_credential import (
    _inspect_requester_inventory,
    _validate_inventory_inputs,
)


SCOPES = {"OLA_CORE", "REVIEW_RESULT"}


def _validate_inputs(tenant_id, credential_id, expected_requester_id,
                     expected_target_scope, expected_active_key_count):
    _validate_inventory_inputs(tenant_id, expected_requester_id, expected_active_key_count)
    if not isinstance(credential_id, str) or _UUID_TEXT.fullmatch(credential_id) is None:
        raise ValueError("target credential ID must be UUID text")
    if credential_id == expected_requester_id:
        raise ValueError("requester pin cannot revoke itself")
    if expected_target_scope not in SCOPES:
        raise ValueError("expected target scope must be OLA_CORE or REVIEW_RESULT")
    if expected_active_key_count < 2:
        raise ValueError("revocation requires at least two active credentials")


def _inspect_revocation(db, tenant_id, credential_id, expected_requester_id,
                        expected_target_scope, expected_active_key_count):
    target = db.get(ApiKey, credential_id)
    if target is None or target.tenant_id != tenant_id:
        raise ValueError("target credential does not belong to this tenant")
    if target.revoked_at is not None:
        raise ValueError("target credential is already revoked")
    if target.access_scope != expected_target_scope:
        raise ValueError("target credential scope differs from the expected scope")
    _inspect_requester_inventory(db, tenant_id, expected_requester_id, expected_active_key_count)
    active_core_count = db.scalar(select(func.count()).select_from(ApiKey).where(
        ApiKey.tenant_id == tenant_id,
        ApiKey.revoked_at.is_(None),
        ApiKey.access_scope == "OLA_CORE"))
    if target.access_scope == "OLA_CORE" and active_core_count <= 1:
        raise ValueError("last active OLA_CORE credential cannot be revoked")
    return target


def _chain_rows(db, tenant_id):
    rows = db.scalars(select(EvidenceRecord).where(
        EvidenceRecord.tenant_id == tenant_id).order_by(EvidenceRecord.seq)).all()
    chain = [{name: getattr(row, name) for name in (
        "id", "tenant_id", "seq", "record_type", "hash_version", "payload_json",
        "prev_hash", "record_hash")} for row in rows]
    if not verify_chain(chain)[0]:
        raise ValueError("evidence chain verification failed")
    return rows


def inspect_tenant_credential_revocation(
    tenant_id: str, *, credential_id: str, expected_requester_id: str,
    expected_target_scope: str, expected_active_key_count: int,
) -> dict:
    _validate_inputs(tenant_id, credential_id, expected_requester_id,
                     expected_target_scope, expected_active_key_count)
    with _database_session() as db:
        _inspect_revocation(db, tenant_id, credential_id, expected_requester_id,
                            expected_target_scope, expected_active_key_count)
        _chain_rows(db, tenant_id)
    return {"schema": "ola.credential-revocation.v1", "status": "DRY_RUN",
            "tenant_id": tenant_id, "credential_id": credential_id,
            "operator_pin_id": expected_requester_id, "access_scope": expected_target_scope,
            "active_key_count": expected_active_key_count, "mutations": 0,
            "assurance": "UNKNOWN", "production_eligible": False}


def revoke_tenant_credential(
    tenant_id: str, *, credential_id: str, expected_requester_id: str,
    expected_target_scope: str, expected_active_key_count: int,
) -> dict:
    _validate_inputs(tenant_id, credential_id, expected_requester_id,
                     expected_target_scope, expected_active_key_count)
    with _database_session(write=True) as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        target = _inspect_revocation(db, tenant_id, credential_id, expected_requester_id,
                                     expected_target_scope, expected_active_key_count)
        rows = _chain_rows(db, tenant_id)
        revoked_at = int(time.time())
        target.revoked_at = revoked_at
        payload = {"credential_id": credential_id, "access_scope": expected_target_scope,
                   "operator_pin_id": expected_requester_id, "revoked_at": revoked_at,
                   "assurance": "UNKNOWN", "production_eligible": False}
        encoded = canonical_json(payload)
        previous = rows[-1].record_hash if rows else GENESIS_HASH
        seq = rows[-1].seq + 1 if rows else 0
        record_id = str(uuid.uuid4())
        record_hash = compute_record_hash(tenant_id, seq, previous, encoded,
            record_id=record_id, record_type="credential.revoked", hash_version=2)
        db.add(EvidenceRecord(id=record_id, tenant_id=tenant_id, seq=seq,
            record_type="credential.revoked", hash_version=2, payload_json=encoded,
            prev_hash=previous, record_hash=record_hash))
        db.commit()
    return {"schema": "ola.credential-revocation.v1", "status": "REVOKED",
            "tenant_id": tenant_id, "credential_id": credential_id,
            "operator_pin_id": expected_requester_id, "access_scope": expected_target_scope,
            "revoked_at": revoked_at, "record_id": record_id, "tip_hash": record_hash,
            "assurance": "UNKNOWN", "production_eligible": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--credential-id", required=True)
    parser.add_argument("--expected-requester-id", required=True)
    parser.add_argument("--expected-target-scope", required=True, choices=sorted(SCOPES))
    parser.add_argument("--expected-active-key-count", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-revocation", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.apply and not args.acknowledge_revocation:
            raise ValueError("--apply requires --acknowledge-revocation")
        if args.apply and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise ValueError("--apply requires interactive stdin and stdout in a private terminal")
        kwargs = {"credential_id": args.credential_id,
                  "expected_requester_id": args.expected_requester_id,
                  "expected_target_scope": args.expected_target_scope,
                  "expected_active_key_count": args.expected_active_key_count}
        operation = revoke_tenant_credential if args.apply else inspect_tenant_credential_revocation
        result = operation(args.tenant_id, **kwargs)
    except ValueError as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError) as exc:
        print("BLOCKED: local operation failed (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
