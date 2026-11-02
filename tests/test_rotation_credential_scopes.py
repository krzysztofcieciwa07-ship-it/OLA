"""Offline rotation preserves credential authority and never reissues revoked keys."""
import json
import os
from pathlib import Path
import sqlite3

import pytest

from app.api_key_crypto import hash_api_key
from scripts import reissue_api_keys_v2 as rotation


def scoped_database(tmp_path):
    path = tmp_path / "credentials # ąę %.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE api_keys (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "key_hash TEXT UNIQUE NOT NULL, access_scope TEXT NOT NULL, revoked_at INTEGER)"
        )
        db.executemany("INSERT INTO api_keys VALUES (?,?,?,?,?)", [
            ("core-active", "tenant-a", "1" * 64, "OLA_CORE", None),
            ("review-active", "tenant-a", "2" * 64, "REVIEW_RESULT", None),
            ("review-revoked", "tenant-a", "3" * 64, "REVIEW_RESULT", 123),
        ])
    return path


def inventory(path):
    with sqlite3.connect(path) as db:
        return db.execute(
            "SELECT id,tenant_id,key_hash,access_scope,revoked_at FROM api_keys ORDER BY id"
        ).fetchall()


def test_rotation_issues_only_active_keys_and_preserves_all_authority(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    before = inventory(path)
    receipt_path, backup_path = tmp_path / "private.json", tmp_path / "backup.db"

    result = rotation.rotate(path, receipt_path, backup_path, True, True)

    receipt = json.loads(receipt_path.read_text())
    assert {row["key_id"] for row in receipt["keys"]} == {"core-active", "review-active"}
    assert {row["key_id"]: row["access_scope"] for row in receipt["keys"]} == {
        "core-active": "OLA_CORE", "review-active": "REVIEW_RESULT",
    }
    assert receipt["number_of_keys"] == result["keys"] == 2
    assert inventory(backup_path) == before
    after = inventory(path)
    assert [(id_, tenant, scope, revoked) for id_, tenant, _, scope, revoked in after] == [
        (id_, tenant, scope, revoked) for id_, tenant, _, scope, revoked in before
    ]
    assert after[-1] == before[-1]
    secrets_by_id = {row["key_id"]: row["api_key"] for row in receipt["keys"]}
    for id_, _, digest, _, revoked in after:
        if revoked is None:
            assert digest == hash_api_key(secrets_by_id[id_])
            assert digest != dict((row[0], row[2]) for row in before)[id_]


def test_scoped_dry_run_counts_only_active_keys_without_writing(tmp_path, monkeypatch):
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    path = scoped_database(tmp_path)
    before = path.read_bytes()
    result = rotation.rotate(path, tmp_path / "private.json", tmp_path / "backup.db", False, False)
    assert result["keys"] == 2
    assert result["status"] == "DRY_RUN" and result["mutations"] == 0
    assert path.read_bytes() == before
    assert not (tmp_path / "private.json").exists()
    assert not (tmp_path / "backup.db").exists()


@pytest.mark.parametrize("scope", ["UNRECOGNIZED", "", None])
def test_invalid_authority_inventory_is_blocked_without_artifacts(tmp_path, scope):
    path = scoped_database(tmp_path)
    with sqlite3.connect(path) as db:
        if scope is None:
            db.execute("ALTER TABLE api_keys RENAME TO original_api_keys")
            db.execute("CREATE TABLE api_keys AS SELECT * FROM original_api_keys")
        db.execute("UPDATE api_keys SET access_scope=? WHERE id='core-active'", (scope,))
    before = path.read_bytes()
    with pytest.raises(rotation.RotationBlocked, match="scope|inventory"):
        rotation.rotate(path, tmp_path / "private.json", tmp_path / "backup.db", False, False)
    assert path.read_bytes() == before
    assert not (tmp_path / "private.json").exists()
    assert not (tmp_path / "backup.db").exists()


@pytest.mark.parametrize("column", ["access_scope", "revoked_at"])
def test_partial_scope_schema_is_not_assumed_to_be_legacy(tmp_path, column):
    path = tmp_path / "partial.db"
    definition = "access_scope TEXT" if column == "access_scope" else "revoked_at INTEGER"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE api_keys (id TEXT PRIMARY KEY, tenant_id TEXT, key_hash TEXT, "
            + definition + ")"
        )
        db.execute("INSERT INTO api_keys (id,tenant_id,key_hash) VALUES (?,?,?)", (
            "key", "tenant", "a" * 64,
        ))
    before = path.read_bytes()
    with pytest.raises(rotation.RotationBlocked, match="schema"):
        rotation.rotate(path, tmp_path / "private.json", tmp_path / "backup.db", False, False)
    assert path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["revoke", "scope"])
def test_authority_change_after_backup_blocks_rotation(tmp_path, monkeypatch, mutation):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    before = inventory(path)
    original_connect = sqlite3.connect

    class ChangeAfterBackup(sqlite3.Connection):
        def backup(self, target, *args, **kwargs):
            super().backup(target, *args, **kwargs)
            with original_connect(path) as writer:
                if mutation == "revoke":
                    writer.execute("UPDATE api_keys SET revoked_at=456 WHERE id='review-active'")
                else:
                    writer.execute("UPDATE api_keys SET access_scope='REVIEW_RESULT' WHERE id='core-active'")

    def connection_with_real_backup_race(*args, **kwargs):
        return original_connect(*args, factory=ChangeAfterBackup, **kwargs)

    monkeypatch.setattr(rotation.sqlite3, "connect", connection_with_real_backup_race)
    with pytest.raises(rotation.RotationBlocked, match="concurrent"):
        rotation.rotate(path, tmp_path / "private.json", tmp_path / "backup.db", True, True)
    with original_connect(path) as db:
        after_hashes = db.execute("SELECT id,key_hash FROM api_keys ORDER BY id").fetchall()
    assert after_hashes == [(row[0], row[2]) for row in before]
    assert not (tmp_path / "private.json").exists()


@pytest.mark.parametrize("apply", [False, True])
def test_database_disappearance_after_file_check_never_creates_empty_db(
    tmp_path, monkeypatch, apply,
):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    saved_path = tmp_path / "preserved.db"
    before = path.read_bytes()
    original_is_file = Path.is_file

    def move_after_check(candidate):
        exists = original_is_file(candidate)
        if candidate == path and exists:
            path.rename(saved_path)
        return exists

    monkeypatch.setattr(Path, "is_file", move_after_check)
    with pytest.raises((rotation.RotationBlocked, sqlite3.Error)):
        rotation.rotate(path, tmp_path / "private.json", tmp_path / "backup.db", apply, apply)
    assert not path.exists(), "opening a missing source must never create a new empty database"
    assert saved_path.read_bytes() == before
    assert not (tmp_path / "private.json").exists()
    assert not (tmp_path / "backup.db").exists()


def marker_database(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE owner_marker (value TEXT NOT NULL)")
        db.execute("INSERT INTO owner_marker VALUES ('preserve this database')")
    return path.read_bytes()


@pytest.mark.parametrize("replacement", ["database", "symlink"])
def test_backup_created_after_validation_is_never_overwritten(tmp_path, monkeypatch, replacement):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    before = path.read_bytes()
    backup_path, receipt_path = tmp_path / "backup.db", tmp_path / "private.json"
    target = tmp_path / "other-owner.db"
    marker = marker_database(target)
    original_destination = rotation._safe_destination

    def replace_after_validation(candidate, source):
        checked = original_destination(candidate, source)
        if checked == backup_path:
            if replacement == "database":
                checked.write_bytes(marker)
            else:
                checked.symlink_to(target)
        return checked

    monkeypatch.setattr(rotation, "_safe_destination", replace_after_validation)
    with pytest.raises((rotation.RotationBlocked, OSError)):
        rotation.rotate(path, receipt_path, backup_path, True, True)

    assert path.read_bytes() == before
    assert backup_path.read_bytes() == marker
    assert target.read_bytes() == marker
    assert backup_path.is_symlink() is (replacement == "symlink")
    assert not receipt_path.exists()


@pytest.mark.parametrize("replacement", ["database", "symlink"])
def test_backup_path_swapped_after_reservation_cannot_redirect_writes(
    tmp_path, monkeypatch, replacement,
):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    before = path.read_bytes()
    backup_path, receipt_path = tmp_path / "backup.db", tmp_path / "private.json"
    target = tmp_path / "other-owner.db"
    marker = marker_database(target)
    original_open = os.open
    swapped = False

    def replace_after_open(candidate, flags, mode=0o777, **kwargs):
        nonlocal swapped
        descriptor = original_open(candidate, flags, mode, **kwargs)
        if Path(candidate) == backup_path and flags & os.O_EXCL:
            backup_path.unlink()
            if replacement == "database":
                backup_path.write_bytes(marker)
            else:
                backup_path.symlink_to(target)
            swapped = True
        return descriptor

    monkeypatch.setattr(rotation.os, "open", replace_after_open)
    with pytest.raises((rotation.RotationBlocked, OSError)):
        rotation.rotate(path, receipt_path, backup_path, True, True)

    assert swapped, "backup destination must be exclusively reserved before writing"
    assert path.read_bytes() == before
    assert backup_path.read_bytes() == marker
    assert target.read_bytes() == marker
    assert backup_path.is_symlink() is (replacement == "symlink")
    assert not receipt_path.exists()


@pytest.mark.parametrize("replacement", ["database", "symlink"])
@pytest.mark.parametrize("force_update_failure", [False, True])
def test_receipt_path_swapped_after_reservation_never_commits_or_deletes_other_file(
    tmp_path, monkeypatch, replacement, force_update_failure,
):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    if force_update_failure:
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TRIGGER refuse_reissue BEFORE UPDATE ON api_keys "
                "BEGIN SELECT RAISE(ABORT, 'forced-update-refusal'); END"
            )
    before = path.read_bytes()
    backup_path, receipt_path = tmp_path / "backup.db", tmp_path / "private.json"
    target = tmp_path / "other-owner.db"
    marker = marker_database(target)
    original_open = os.open
    swapped = False

    def replace_after_open(candidate, flags, mode=0o777, **kwargs):
        nonlocal swapped
        descriptor = original_open(candidate, flags, mode, **kwargs)
        if Path(candidate) == receipt_path and flags & os.O_EXCL:
            receipt_path.unlink()
            if replacement == "database":
                receipt_path.write_bytes(marker)
            else:
                receipt_path.symlink_to(target)
            swapped = True
        return descriptor

    monkeypatch.setattr(rotation.os, "open", replace_after_open)
    with pytest.raises((rotation.RotationBlocked, sqlite3.Error)):
        rotation.rotate(path, receipt_path, backup_path, True, True)

    assert swapped, "receipt destination must be exclusively reserved before writing"
    assert path.read_bytes() == before
    assert receipt_path.exists(), "rollback must never unlink another owner's replacement"
    assert receipt_path.read_bytes() == marker
    assert target.read_bytes() == marker
    assert receipt_path.is_symlink() is (replacement == "symlink")


def test_failed_update_preserves_private_receipt_and_marks_it_not_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    path = scoped_database(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TRIGGER refuse_reissue BEFORE UPDATE ON api_keys "
            "BEGIN SELECT RAISE(ABORT, 'private-driver-error'); END"
        )
    before = path.read_bytes()
    receipt_path = tmp_path / "private.json"

    with pytest.raises(rotation.RotationBlocked, match="NOT_VALID") as failure:
        rotation.rotate(path, receipt_path, tmp_path / "backup.db", True, True)

    assert path.read_bytes() == before
    assert receipt_path.is_file()
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    private_receipt = json.loads(receipt_path.read_text())
    assert private_receipt["number_of_keys"] == 2
    assert "private-driver-error" not in str(failure.value)
    assert all(row["api_key"] not in str(failure.value) for row in private_receipt["keys"])
