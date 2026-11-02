"""Additive credential access migration preserves historical rows and key hashes."""
import sqlite3

import pytest
from sqlalchemy import create_engine

from app import database


def migration():
    feature = getattr(database, "ensure_api_key_access_schema", None)
    assert callable(feature), "credential access migration is not implemented"
    return feature


def test_legacy_credentials_migrate_to_core_without_rewriting_hashes(tmp_path, monkeypatch):
    path = tmp_path / "legacy-credentials.sqlite"
    original = ("credential-old", "tenant-old", "a" * 64)
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE api_keys (id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,key_hash TEXT NOT NULL UNIQUE)")
        raw.execute("INSERT INTO api_keys VALUES (?,?,?)", original)
    migrated = create_engine("sqlite:///" + str(path))
    monkeypatch.setattr(database, "engine", migrated)
    try:
        migration()()
        migration()()
        with migrated.begin() as connection:
            rows = connection.exec_driver_sql(
                "SELECT id,tenant_id,key_hash,access_scope,revoked_at FROM api_keys"
            ).all()
        assert [tuple(row) for row in rows] == [(*original, "OLA_CORE", None)]
    finally:
        migrated.dispose()


def test_partially_migrated_database_preserves_existing_reviewer_and_revocation(tmp_path, monkeypatch):
    path = tmp_path / "partial.sqlite"
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE api_keys (id TEXT PRIMARY KEY,tenant_id TEXT,key_hash TEXT,access_scope TEXT NOT NULL)")
        raw.execute("INSERT INTO api_keys VALUES ('reviewer','tenant',?,'REVIEW_RESULT')", ("b" * 64,))
    migrated = create_engine("sqlite:///" + str(path))
    monkeypatch.setattr(database, "engine", migrated)
    try:
        migration()()
        with migrated.begin() as connection:
            connection.exec_driver_sql("UPDATE api_keys SET revoked_at=123 WHERE id='reviewer'")
        migration()()
        with migrated.begin() as connection:
            actual = connection.exec_driver_sql("SELECT id,key_hash,access_scope,revoked_at FROM api_keys").one()
        assert tuple(actual) == ("reviewer", "b" * 64, "REVIEW_RESULT", 123)
    finally:
        migrated.dispose()


@pytest.mark.parametrize("scope", ["ADMIN", "", None])
def test_invalid_preexisting_scope_blocks_migration_without_promoting_it(tmp_path, monkeypatch, scope):
    path = tmp_path / "invalid.sqlite"
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE api_keys (id TEXT PRIMARY KEY,tenant_id TEXT,key_hash TEXT,access_scope TEXT)")
        raw.execute("INSERT INTO api_keys VALUES ('invalid','tenant',?,?)", ("c" * 64, scope))
    migrated = create_engine("sqlite:///" + str(path))
    monkeypatch.setattr(database, "engine", migrated)
    try:
        with pytest.raises(RuntimeError, match="scope"):
            migration()()
        with sqlite3.connect(path) as raw:
            assert raw.execute("SELECT id,tenant_id,key_hash,access_scope FROM api_keys").fetchone() == (
                "invalid", "tenant", "c" * 64, scope,
            )
    finally:
        migrated.dispose()
