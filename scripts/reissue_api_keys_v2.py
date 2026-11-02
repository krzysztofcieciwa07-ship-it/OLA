#!/usr/bin/env python3
"""OFFLINE ONLY: reissue active OLA SQLite API keys for v2 credential hashing.

This is an explicit destructive credential rotation: previous client key text
WILL STOP WORKING. Preserve key_id/tenant_id for audit and 4-eyes approvals.
DO NOT run against a live database; stop every writer, take an external
snapshot, then run --apply. Never print/reveal tokens in console or CI logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(api_keys)").fetchall()}
    authority_columns = {"access_scope", "revoked_at"}.intersection(columns)
    if authority_columns and authority_columns != {"access_scope", "revoked_at"}:
        raise RotationBlocked("incomplete API-key authority schema")
    authority_sql = "access_scope,revoked_at" if authority_columns else "'OLA_CORE',NULL"
    rows = conn.execute(
        "SELECT id,tenant_id,key_hash," + authority_sql + " FROM api_keys ORDER BY id"
    ).fetchall()
    if any(not isinstance(id_, str) or not isinstance(tenant, str)
           or not isinstance(digest, str) or len(digest) != 64
           or scope not in {"OLA_CORE", "REVIEW_RESULT"}
           for id_, tenant, digest, scope, _ in rows):
        raise RotationBlocked("malformed existing API-key inventory")
    return rows

def _assert_reserved_file(path: Path, identity, kind):
    try:
        current = path.lstat()
    except OSError:
        raise RotationBlocked("reserved " + kind + " destination disappeared") from None
    if (not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != identity):
        raise RotationBlocked("reserved " + kind + " destination changed")

def _assert_reserved_backup(path: Path, identity):
    _assert_reserved_file(path, identity, "backup")

def _write_backup(db, backup: Path):
    # Reserve the final pathname atomically. Never let sqlite3.connect() create
    # or reopen it: a replacement between validation and open could otherwise
    # redirect backup() into an unrelated database or symlink target.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(backup), flags, 0o600)
    try:
        reserved = os.fstat(descriptor)
        identity = (reserved.st_dev, reserved.st_ino)
        _assert_reserved_backup(backup, identity)
        # SQLite needs its own database connection. Keep that staging file in
        # a private 0700 directory and copy only through the reserved descriptor.
        with tempfile.TemporaryDirectory(prefix=".ola-backup-", dir=backup.parent) as folder:
            staging = Path(folder) / "snapshot.db"
            staging_fd = os.open(str(staging), flags, 0o600)
            os.close(staging_fd)
            snapshot = sqlite3.connect(staging.as_uri() + "?mode=rw", uri=True)
            try:
                db.backup(snapshot)
                snapshot.commit()
            finally:
                snapshot.close()
            _assert_reserved_backup(backup, identity)
            with staging.open("rb") as source, os.fdopen(os.dup(descriptor), "wb") as destination:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            _assert_reserved_backup(backup, identity)
        return identity
    finally:
        # Do not unlink the public path on error: it may now name someone
        # else's file. A partial reservation is retained for owner inspection.
        os.close(descriptor)

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
    # The existence check is advisory; SQLite itself must refuse a vanished
    # source instead of silently creating a new empty deployment database.
    source_uri = db_path.as_uri() + ("?mode=rw" if apply else "?mode=ro")
    db = sqlite3.connect(source_uri, uri=True, timeout=2)
    try:
        inventory = _inventory(db)
        active = [row for row in inventory if row[4] is None]
        if not apply:
            return {"status": "DRY_RUN", "keys": len(active),
                    "key_ids_preserved": True, "mutations": 0}
        if os.environ.get("OLA_API_KEY_PEPPER", "") == "":
            raise RotationBlocked("deployment pepper is not configured")
        # Assert the hash function and deployment pepper before any backup/write.
        hash_api_key("rotation-preflight")
        old_mode = os.umask(0o077)
        try:
            backup_identity = _write_backup(db, backup)
            # Existing writers must be stopped; abort if inventory changed after backup.
            db.execute("BEGIN EXCLUSIVE")
            current = _inventory(db)
            if current != inventory:
                raise RotationBlocked("concurrent key changes detected since backup")
            credentials = []
            rotated = []
            for id_, tenant_id, _, scope, _ in active:
                secret = "ola2_" + secrets.token_urlsafe(48)
                digest = hash_api_key(secret)
                credentials.append({"key_id": id_, "tenant_id": tenant_id,
                                    "access_scope": scope, "api_key": secret})
                rotated.append((digest, id_))
            receipt = {"schema": "ola-api-keys-v2/offline-reissue",
                       "keys": credentials, "number_of_keys": len(credentials)}
            receipt_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(output), receipt_flags, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    reserved = os.fstat(stream.fileno())
                    receipt_identity = (reserved.st_dev, reserved.st_ino)
                    _assert_reserved_file(output, receipt_identity, "receipt")
                    json.dump(receipt, stream, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                _assert_reserved_file(output, receipt_identity, "receipt")
                for digest, id_ in rotated:
                    cursor = db.execute("UPDATE api_keys SET key_hash=? WHERE id=?", (digest, id_))
                    if cursor.rowcount != 1:
                        raise RotationBlocked("key row changed during reissue")
                _assert_reserved_backup(backup, backup_identity)
                _assert_reserved_file(output, receipt_identity, "receipt")
                db.commit()
            except BaseException as exc:
                db.rollback()
                # The public pathname may now belong to another owner. Keep
                # both replacements and our own private reservation; even an
                # identity check followed by unlink would introduce a new race.
                # A receipt written before rollback must never be treated as
                # evidence that its keys became active.
                if isinstance(exc, Exception):
                    raise RotationBlocked(
                        "rotation failed; retained receipt is NOT_VALID; inspect inventory before retry"
                    ) from None
                raise
        finally:
            os.umask(old_mode)
        # Never write raw tokens into logs. Owner must distribute securely and
        # erase the 0600 receipt after every client confirms credential rotation.
        return {"status": "ROTATED_OFFLINE", "keys": len(active),
                "key_ids_preserved": True, "backup_written": True,
                "receipt_written": True, "legacy_auth_fallback": False}
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--runtime-stopped", action="store_true",
                        help="Operator asserts ALL OLA writers have been stopped")
    args = parser.parse_args()
    try:
        result = rotate(args.db,args.receipt,args.backup,args.apply,args.runtime_stopped)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RotationBlocked, sqlite3.Error, OSError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
