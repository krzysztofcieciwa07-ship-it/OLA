"""Offline reissue cannot silently overwrite keys or discard tenant/key IDs."""
import json
import os
from pathlib import Path
import sqlite3
import stat

import pytest

from app.api_key_crypto import hash_api_key
from scripts import reissue_api_keys_v2 as migration
from scripts.reissue_api_keys_v2 import RotationBlocked, rotate, verify_receipt


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "production-copy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE api_keys (id TEXT PRIMARY KEY, tenant_id TEXT, key_hash TEXT UNIQUE)")
        db.executemany(
            "INSERT INTO api_keys VALUES (?,?,?)",
            [("key-1", "tenant-a", "1" * 64),
             ("key-2", "tenant-b", "2" * 64)],
        )
    return path


def test_dry_run_is_read_only_without_pepper(tmp_path, monkeypatch):
    monkeypatch.delenv("OLA_API_KEY_PEPPER", raising=False)
    db = _db(tmp_path)
    before = db.read_bytes()
    result = rotate(db, tmp_path/"tokens.json", tmp_path/"safe.db",False,False)
    assert result == {
        "status":"DRY_RUN","keys":2,"key_ids_preserved":True,"mutations":0}
    assert db.read_bytes() == before
    assert not (tmp_path/"tokens.json").exists()
    assert not (tmp_path/"safe.db").exists()


def test_rotation_requires_explicit_offline_operator_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    db = _db(tmp_path)
    with pytest.raises(RotationBlocked):
        rotate(db,tmp_path/"tokens.json",tmp_path/"backup.db",True,False)


def test_rotation_preserves_legacy_backup_and_issues_new_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    db = _db(tmp_path)
    result = rotate(db,tmp_path/"tokens.json",tmp_path/"backup.db",True,True)
    assert result["status"] == "ROTATED_OFFLINE"
    assert result["legacy_auth_fallback"] is False
    assert (tmp_path/"tokens.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path/"backup.db").stat().st_mode & 0o777 == 0o600
    rows_before = sqlite3.connect(tmp_path/"backup.db").execute("SELECT * FROM api_keys ORDER BY id").fetchall()
    rows_after = sqlite3.connect(db).execute("SELECT * FROM api_keys ORDER BY id").fetchall()
    assert [(a,b) for a,b,_ in rows_after] == [(a,b) for a,b,_ in rows_before]
    assert [v for _,_,v in rows_before] == ["1"*64,"2"*64]
    receipt = json.loads((tmp_path/"tokens.json").read_text())
    assert len(receipt["keys"]) == 2
    assert all(row["api_key"].startswith("ola2_") for row in receipt["keys"])
    assert len({row["api_key"] for row in receipt["keys"]}) == 2
    assert [hash_api_key(row["api_key"]) for row in receipt["keys"]] == [v for _,_,v in rows_after]


def test_refuse_existing_sensitive_receipt_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "P" * 64)
    db = _db(tmp_path)
    sensitive = tmp_path / "tokens.json"
    sensitive.write_text("do not overwrite")
    with pytest.raises(RotationBlocked):
        rotate(db,sensitive,tmp_path/"backup.db",True,True)
    assert sensitive.read_text() == "do not overwrite"
    assert not (tmp_path/"backup.db").exists()


def _rows(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT * FROM api_keys ORDER BY id").fetchall()


def test_backup_created_after_preflight_cannot_be_overwritten(tmp_path, monkeypatch):
    db = _db(tmp_path)
    before = _rows(db)
    backup = tmp_path / "backup.db"
    original_link = os.link

    def competing_create(source, destination, *args, **kwargs):
        if Path(destination) == backup:
            backup.write_bytes(b"other operator's backup")
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", competing_create)
    with pytest.raises(FileExistsError):
        rotate(db, tmp_path/"tokens.json", backup, True, True)
    assert backup.read_bytes() == b"other operator's backup"
    assert _rows(db) == before
    assert not (tmp_path/"tokens.json").exists()


def test_raced_backup_symlink_cannot_overwrite_an_unrelated_database(tmp_path, monkeypatch):
    db = _db(tmp_path)
    before = _rows(db)
    backup, victim = tmp_path/"backup.db", tmp_path/"unrelated.db"
    with sqlite3.connect(victim) as other:
        other.execute("CREATE TABLE evidence (value TEXT)")
        other.execute("INSERT INTO evidence VALUES ('must survive')")
    original_link = os.link

    def competing_link(source, destination, *args, **kwargs):
        if Path(destination) == backup:
            backup.symlink_to(victim)
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(FileExistsError):
        rotate(db, tmp_path/"tokens.json", backup, True, True)
    assert _rows(db) == before
    with sqlite3.connect(victim) as other:
        assert other.execute("SELECT * FROM evidence").fetchall() == [("must survive",)]
    assert not (tmp_path/"tokens.json").exists()


def test_successful_commit_followed_by_interrupt_keeps_valid_receipt(tmp_path, monkeypatch):
    db = _db(tmp_path)
    receipt, backup = tmp_path/"tokens.json", tmp_path/"backup.db"
    original_connect = sqlite3.connect

    class InterruptedCommit(sqlite3.Connection):
        def commit(self):
            super().commit()
            raise KeyboardInterrupt("synthetic interrupt after durable commit")

    def connect(database, *args, **kwargs):
        if str(database) == str(db):
            kwargs["factory"] = InterruptedCommit
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(KeyboardInterrupt):
        rotate(db, receipt, backup, True, True)
    assert verify_receipt(db, receipt) == {
        "status": "RECEIPT_VERIFIED", "keys": 2, "client_delivery": "NOT_ATTESTED"}
    assert [digest for _, _, digest in _rows(backup)] == ["1"*64, "2"*64]


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_snapshot_covers_evidence_and_holds_writer_lock(tmp_path, monkeypatch, journal_mode):
    db = _db(tmp_path)
    backup = tmp_path / "backup.db"
    with sqlite3.connect(db) as source:
        source.execute("PRAGMA journal_mode=" + journal_mode)
        source.execute("CREATE TABLE evidence (event TEXT)")
        source.execute("INSERT INTO evidence VALUES ('before rotation')")
    original_sync = migration._sync_file_and_directory
    lock_checked = []

    def sync(path):
        if path == backup:
            with sqlite3.connect(db, timeout=0) as competing:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    competing.execute("INSERT INTO evidence VALUES ('unexpected writer')")
            with sqlite3.connect(backup) as saved:
                assert saved.execute("SELECT * FROM evidence").fetchall() == [("before rotation",)]
            lock_checked.append(True)
        original_sync(path)

    monkeypatch.setattr(migration, "_sync_file_and_directory", sync)
    rotate(db, tmp_path/"tokens.json", backup, True, True)
    assert lock_checked == [True]
    assert verify_receipt(db, tmp_path/"tokens.json")["status"] == "RECEIPT_VERIFIED"


@pytest.mark.parametrize("failure_at", ["backup", "receipt", "commit"])
def test_precommit_failure_keeps_original_keys(tmp_path, monkeypatch, failure_at):
    db = _db(tmp_path)
    before = _rows(db)
    backup, receipt = tmp_path/"backup.db", tmp_path/"tokens.json"
    original_sync, original_connect = migration._sync_file_and_directory, sqlite3.connect

    def sync(path):
        if (failure_at == "backup" and path == backup or
                failure_at == "receipt" and path == receipt):
            raise OSError("synthetic durability failure")
        original_sync(path)

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise OSError("synthetic failure before commit")

    def connect(database, *args, **kwargs):
        if failure_at == "commit" and str(database) == str(db):
            kwargs["factory"] = FailedCommit
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(migration, "_sync_file_and_directory", sync)
    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(OSError):
        rotate(db, receipt, backup, True, True)
    assert _rows(db) == before
    assert _rows(backup) == before
    if receipt.exists():
        with pytest.raises(RotationBlocked, match="does not match"):
            verify_receipt(db, receipt)


def test_files_and_parent_directories_are_synced_before_commit(tmp_path, monkeypatch):
    db = _db(tmp_path)
    syncs = []
    original_fsync, original_connect = os.fsync, sqlite3.connect

    def fsync(fd):
        syncs.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        original_fsync(fd)

    class CheckedCommit(sqlite3.Connection):
        def commit(self):
            assert syncs == ["file", "directory", "file", "file", "directory"]
            return super().commit()

    def connect(database, *args, **kwargs):
        if str(database) == str(db):
            kwargs["factory"] = CheckedCommit
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(sqlite3, "connect", connect)
    rotate(db, tmp_path/"tokens.json", tmp_path/"backup.db", True, True)


def test_recovery_rejects_changed_pepper_or_duplicate_identity(tmp_path, monkeypatch):
    db = _db(tmp_path)
    receipt = tmp_path/"tokens.json"
    rotate(db, receipt, tmp_path/"backup.db", True, True)
    with monkeypatch.context() as changed:
        changed.setenv("OLA_API_KEY_PEPPER", "different-deployment-pepper-" * 3)
        with pytest.raises(RotationBlocked):
            verify_receipt(db, receipt)
    document = json.loads(receipt.read_text())
    document["keys"][1] = document["keys"][0]
    receipt.write_text(json.dumps(document))
    with pytest.raises(RotationBlocked, match="duplicate"):
        verify_receipt(db, receipt)


def test_rotated_tokens_preserve_auth_and_independent_reviewer_identity(tmp_path, monkeypatch, local_binding_source):
    import importlib
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import ApiKey, Tenant
    from conftest import bound_candidate_fields

    main = importlib.import_module("app.main")
    db_path = tmp_path / "identities.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(main, "SessionLocal", session)
    try:
        with session() as db:
            db.add_all([Tenant(id="tenant-a", name="A"), Tenant(id="tenant-b", name="B")])
            db.flush()
            db.add_all([
                ApiKey(id="requester", tenant_id="tenant-a", key_hash="1"*64),
                ApiKey(id="reviewer", tenant_id="tenant-a", key_hash="2"*64),
                ApiKey(id="outsider", tenant_id="tenant-b", key_hash="3"*64),
            ])
            db.commit()
        bound_fields = bound_candidate_fields("tenant-a", "requester", "pending-before-rotation")
        tip = main.append_record("tenant-a", "decision.candidate", {
            "run_id": "pending-before-rotation", "requester_id": "requester",
            **bound_fields,
            "status_fields": {"RUNTIME": "VERIFIED", "EVIDENCE": "VERIFIED",
                              "REPLAY_INTEGRITY": "VERIFIED", "POLICY": "VERIFIED",
                              "HUMAN_GATE": "REVIEW", "EXECUTION_ALLOWED": "REVIEW"},
            "candidate_status": "REVIEW",
        })["record_hash"]
        engine.dispose()
        receipt = tmp_path / "tokens.json"
        rotate(db_path, receipt, tmp_path/"backup.db", True, True)
        tokens = {key["key_id"]: key["api_key"] for key in json.loads(receipt.read_text())["keys"]}
        assert main.identity_from_key(tokens["requester"]) == ("tenant-a", "requester")
        assert main.bearer_identity("Bearer " + tokens["reviewer"]) == ("tenant-a", "reviewer")
        client = TestClient(main.app)
        evidence = client.post("/evidence", headers={"X-API-Key": tokens["outsider"]},
                               json={"record_type": "generic", "payload": {"after": "rotation"}})
        assert evidence.status_code == 200
        assert evidence.json()["tenant_id"] == "tenant-b"
        for role, status in [("requester", 403), ("outsider", 409), ("reviewer", 200)]:
            response = client.post("/nina-run/pending-before-rotation/approve",
                                   headers={"Authorization": "Bearer " + tokens[role]},
                                   json={"tip_hash": tip, "scope": "review-result",
                                         "report_sha256": bound_fields["decision_report_v2"]["report_sha256"]})
            assert response.status_code == status, response.text
    finally:
        engine.dispose()


def test_cli_reports_status_without_credentials(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path)
    receipt = tmp_path/"tokens.json"
    monkeypatch.setattr(migration.sys, "argv", ["reissue_api_keys_v2.py", "--db", str(db),
                        "--receipt", str(receipt), "--backup", str(tmp_path/"backup.db"),
                        "--apply", "--runtime-stopped"])
    assert migration.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "ROTATED_OFFLINE"
    for key in json.loads(receipt.read_text())["keys"]:
        assert key["api_key"] not in captured.out + captured.err
