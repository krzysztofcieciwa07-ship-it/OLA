from types import SimpleNamespace

import pytest

from app import database


def test_database_url_supports_postgres_and_preserves_sqlite_fallback():
    resolver = getattr(database, "database_url_from_env", None)
    assert callable(resolver), "database URL resolver is missing"

    assert resolver({"OLA_DATABASE_URL": "postgresql://ola:secret@db:5432/ola"}) == (
        "postgresql+psycopg://ola:secret@db:5432/ola"
    )
    assert resolver({"DATABASE_URL": "postgres://ola:secret@db:5432/ola"}) == (
        "postgresql+psycopg://ola:secret@db:5432/ola"
    )
    assert resolver({"OLA_EG_DB_PATH": "/tmp/ola-test.db"}) == "sqlite:////tmp/ola-test.db"


def test_tenant_advisory_lock_key_is_stable_signed_64_bit_and_tenant_scoped():
    key_fn = getattr(database, "tenant_advisory_lock_key", None)
    assert callable(key_fn), "PostgreSQL tenant lock-key function is missing"

    first = key_fn("tenant-alpha")
    assert first == key_fn("tenant-alpha")
    assert first != key_fn("tenant-beta")
    assert -(2**63) <= first < 2**63


def test_postgres_write_transaction_acquires_tenant_advisory_xact_lock():
    begin = getattr(database, "begin_write_transaction", None)
    key_fn = getattr(database, "tenant_advisory_lock_key", None)
    assert callable(begin), "database transaction lock helper is missing"
    assert callable(key_fn), "PostgreSQL tenant lock-key function is missing"

    statements = []

    class FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def get_bind(self):
            return self.bind

        def execute(self, statement, params=None):
            statements.append((str(statement), params))

    begin(FakeSession(), tenant_id="tenant-alpha")

    assert len(statements) == 1
    sql, params = statements[0]
    assert "pg_advisory_xact_lock" in sql
    assert params == {"lock_key": key_fn("tenant-alpha")}


def test_postgres_write_transaction_rejects_missing_tenant_lock_scope():
    begin = getattr(database, "begin_write_transaction", None)
    assert callable(begin), "database transaction lock helper is missing"

    class FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def get_bind(self):
            return self.bind

        def execute(self, statement, params=None):
            raise AssertionError("must not acquire an unscoped PostgreSQL write transaction")

    with pytest.raises(ValueError, match="tenant_id"):
        begin(FakeSession())


def test_sqlite_write_transaction_keeps_begin_immediate():
    begin = database.begin_write_transaction
    executed = []

    class FakeConnection:
        def exec_driver_sql(self, statement):
            executed.append(statement)

    class FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def get_bind(self):
            return self.bind

        def connection(self):
            return FakeConnection()

    begin(FakeSession(), tenant_id="tenant-alpha")
    assert executed == ["BEGIN IMMEDIATE"]


def test_postgres_runtime_schema_only_verifies_and_never_runs_ddl(monkeypatch):
    calls = []

    class FakeEngine:
        dialect = SimpleNamespace(name="postgresql")

    monkeypatch.setattr(database, "engine", FakeEngine())
    monkeypatch.setattr(
        database, "verify_postgres_schema",
        lambda target: calls.append(("verify", target)),
    )
    monkeypatch.setattr(
        database.Base.metadata, "create_all",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("runtime must not run DDL")),
    )

    database.prepare_runtime_schema()

    assert len(calls) == 1
    assert calls[0][0] == "verify"
    assert isinstance(calls[0][1], FakeEngine)


def test_database_url_rejects_unsupported_dialects():
    with pytest.raises(ValueError, match="PostgreSQL/psycopg or SQLite"):
        database.database_url_from_env({"OLA_DATABASE_URL": "mysql://ola:secret@db/ola"})
