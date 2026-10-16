#!/usr/bin/env python3
"""OFFLINE ONLY: reissue all OLA SQLite API keys for v2 credential hashing.

This is an explicit destructive credential rotation: previous client key text
WILL STOP WORKING. Preserve key_id/tenant_id for audit and 4-eyes approvals.
DO NOT run against a live database; stop every writer, take an external
snapshot, then run --apply. Never print/reveal tokens in console or CI logs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import re
import sqlite3
import sys
import tempfile

# Keep direct `python scripts/reissue_api_keys_v2.py` invocation independent of PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api_key_crypto import hash_api_key

class RotationBlocked(RuntimeError):
    pass

def _safe_destination(path: Path, source: Path):
    path = path.absolute()
    if path == source or path.exists() or path.is_symlink():
        raise RotationBlocked("destination already exists or overlaps database")
    if not path.parent.is_dir():
        raise RotationBlocked("destination parent directory missing")
    return path

def _inventory(conn):
    check = conn.execute("PRAGMA integrity_check").fetchone()
    if not check or check[0] != "ok":
        raise RotationBlocked("database integrity_check failed")
    rows = conn.execute("SELECT id, tenant_id, key_hash FROM api_keys ORDER BY id").fetchall()
    if any(not isinstance(id_, str) or not isinstance(tenant, str)
           or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
           for id_, tenant, digest in rows):
        raise RotationBlocked("malformed existing API-key inventory")
    return rows

def _sync_file_and_directory(path: Path):
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def verify_receipt(db_path: Path, receipt_path: Path):
    """Read-only recovery check; never claims client delivery or production GO."""
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "ola-api-keys-v2/offline-reissue":
        raise RotationBlocked("unsupported receipt")
    credentials = receipt.get("keys")
    if not isinstance(credentials, list) or receipt.get("number_of_keys") != len(credentials):
        raise RotationBlocked("malformed receipt")
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = _inventory(db)
    provided = {}
    for item in credentials:
        if item["key_id"] in provided:
            raise RotationBlocked("duplicate receipt key")
        provided[item["key_id"]] = (item["tenant_id"], hash_api_key(item["api_key"]))
    if provided != {id_: (tenant, digest) for id_, tenant, digest in rows}:
        raise RotationBlocked("receipt does not match database and deployment pepper")
    return {"status": "RECEIPT_VERIFIED", "keys": len(rows), "client_delivery": "NOT_ATTESTED"}


def rotate(db_path: Path, output: Path, backup: Path, apply: bool, offline_confirmed: bool):
    db_path = db_path.absolute()
    if not db_path.is_file() or db_path.is_symlink():
        raise RotationBlocked("source database not a regular file")
    output = _safe_destination(output, db_path)
    backup = _safe_destination(backup, db_path)
    if output == backup:
        raise RotationBlocked("backup and token output must differ")
    if apply and (not offline_confirmed or os.name != "posix"):
        raise RotationBlocked("requires --runtime-stopped and POSIX 0600 permissions")
    db = sqlite3.connect(str(db_path), timeout=2)
    try:
        inventory = _inventory(db)
        if not apply:
            return {"status": "DRY_RUN", "keys": len(inventory),
                    "key_ids_preserved": True, "mutations": 0}
        if os.environ.get("OLA_API_KEY_PEPPER", "") == "":
            raise RotationBlocked("deployment pepper is not configured")
        # Assert the hash function and deployment pepper before any backup/write.
        hash_api_key("rotation-preflight")
        # Acquire the writer lock BEFORE the snapshot, retaining it until commit.
        # A separate read connection can back up DELETE and WAL databases while
        # this connection holds BEGIN IMMEDIATE; backing up this writer stalls.
        db.execute("BEGIN IMMEDIATE")
        inventory = _inventory(db)
        # SQLite reopens filenames. Build inside a private 0700 directory so a
        # competing destination cannot redirect that open into an unrelated DB.
        # Publish with link(), whose creation is atomic and never replaces a
        # destination (including symlinks) created after preflight.
        with tempfile.TemporaryDirectory(prefix="ola-key-backup-", dir=backup.parent) as staging:
            staged = Path(staging) / "snapshot.db"
            fd = os.open(str(staged), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(str(staged))) as snapshot:
                    source.backup(snapshot)
                    if _inventory(snapshot) != inventory:
                        raise RotationBlocked("backup inventory mismatch")
            os.link(staged, backup)
        _sync_file_and_directory(backup)
        credentials = []
        rotated = []
        for id_, tenant_id, _ in inventory:
            secret = "ola2_" + secrets.token_urlsafe(48)
            digest = hash_api_key(secret)
            credentials.append({"key_id": id_, "tenant_id": tenant_id, "api_key": secret})
            rotated.append((digest, id_))
        receipt = {"schema": "ola-api-keys-v2/offline-reissue",
                   "keys": credentials, "number_of_keys": len(credentials)}
        fd = os.open(str(output), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _sync_file_and_directory(output)
        for digest, id_ in rotated:
            cursor = db.execute("UPDATE api_keys SET key_hash=? WHERE id=?", (digest, id_))
            if cursor.rowcount != 1:
                raise RotationBlocked("key row changed during reissue")
        # Never delete the receipt on an exception: commit can succeed before an
        # interrupt is delivered. Retained credentials allow offline verification
        # and recovery in either state, without resetting client identities.
        db.commit()
        # Never write raw tokens into logs. Owner must distribute securely and
        # erase the 0600 receipt after every client confirms credential rotation.
        return {"status": "ROTATED_OFFLINE", "keys": len(inventory),
                "key_ids_preserved": True, "backup_written": True,
                "receipt_written": True, "legacy_auth_fallback": False}
    finally:
        db.close()  # Rolls back an uncommitted transaction; keeps recovery files.

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-receipt", action="store_true")
    parser.add_argument("--runtime-stopped", action="store_true",
                        help="Operator asserts ALL OLA writers have been stopped")
    args = parser.parse_args()
    try:
        if args.verify_receipt:
            result = verify_receipt(args.db, args.receipt)
        else:
            if args.backup is None:
                parser.error("--backup is required for rotation/dry-run")
            result = rotate(args.db,args.receipt,args.backup,args.apply,args.runtime_stopped)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print("BLOCKED: " + type(exc).__name__, file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
