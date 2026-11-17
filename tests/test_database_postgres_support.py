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


def test_postgres_session_context_uses_api_key_evidence_not_tenant_id_gucs():
    from app.database import _apply_postgres_tenant_context
    from app.tenant_context import (
        set_api_key_context, reset_database_auth_context,
        set_current_tenant_id, reset_current_tenant_id,
    )

    calls = []

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, statement, params=None):
            calls.append((str(statement), params))

    connection = FakeConnection()

    tenant_token = set_current_tenant_id("tenant-alpha")
    try:
        _apply_postgres_tenant_context(None, None, connection)
        assert calls == [], "a caller-supplied tenant id must not establish PostgreSQL RLS"
    finally:
        reset_current_tenant_id(tenant_token)

    auth_token = set_api_key_context("a" * 64)
    try:
        _apply_postgres_tenant_context(None, None, connection)
    finally:
        reset_database_auth_context(auth_token)
    assert calls == [
        ("SELECT ola_establish_api_key_context(:key_hash)", {"key_hash": "a" * 64}),
    ]


def test_postgres_session_context_uses_database_claim_for_worker():
    from app.database import _apply_postgres_tenant_context
    from app.tenant_context import set_worker_claim_context, reset_database_auth_context

    calls = []

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, statement, params=None):
            calls.append((str(statement), params))

    token = set_worker_claim_context("job-123", "a" * 32, 900)
    try:
        _apply_postgres_tenant_context(None, None, FakeConnection())
    finally:
        reset_database_auth_context(token)
    assert calls == [
        (
            "SELECT ola_establish_worker_context(:job_id, :claim_token, :stale_after_seconds)",
            {"job_id": "job-123", "claim_token": "a" * 32, "stale_after_seconds": 900},
        )
    ]


def test_postgres_session_context_uses_stored_checkout_binding_for_stripe():
    from app.database import _apply_postgres_tenant_context
    from app.tenant_context import set_checkout_context, reset_database_auth_context

    calls = []

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, statement, params=None):
            calls.append((str(statement), params))

    token = set_checkout_context("order-123", "cs_test_123")
    try:
        _apply_postgres_tenant_context(None, None, FakeConnection())
    finally:
        reset_database_auth_context(token)
    assert calls == [
        (
            "SELECT ola_establish_checkout_context(:order_id, :session_id)",
            {"order_id": "order-123", "session_id": "cs_test_123"},
        )
    ]


def test_role_membership_diagnostic_includes_grantor_and_admin_option():
    formatter = getattr(database, "_format_role_membership_violations", None)
    assert callable(formatter), "role membership diagnostic formatter is missing"

    details = formatter([{
        "member": "ola_migrator",
        "granted_role": "ola_runtime",
        "grantor": "cloud_admin",
        "admin_option": True,
        "inherit_option": False,
        "set_option": False,
    }])

    assert details == (
        "ola_migrator->ola_runtime "
        "(grantor=cloud_admin, admin_option=true, inherit_option=false, set_option=false)"
    )


def test_provider_managed_migration_membership_is_narrowly_allowlisted():
    validator = getattr(database, "_role_membership_violations", None)
    assert callable(validator), "provider-managed role membership validator is missing"

    allowed = [{
        "member": "ola_migrator",
        "granted_role": "ola_runtime",
        "grantor": "cloud_admin",
        "admin_option": True,
        "inherit_option": False,
        "set_option": False,
    }, {
        "member": "ola_migrator",
        "granted_role": "ola_worker",
        "grantor": "cloud_admin",
        "admin_option": True,
        "inherit_option": False,
        "set_option": False,
    }]
    assert validator(
        allowed, runtime_role="ola_runtime",
        worker_role="ola_worker", migration_role="ola_migrator",
    ) == []
    assert validator(
        [], runtime_role="ola_runtime",
        worker_role="ola_worker", migration_role="ola_migrator",
    ) == []

    unsafe_variants = [
        {**allowed[0], "admin_option": False},
        {**allowed[0], "set_option": True},
        {**allowed[0], "inherit_option": True},
        {**allowed[0], "grantor": "untrusted_role"},
        {**allowed[0], "member": "untrusted_role"},
        {**allowed[0], "member": "ola_runtime", "granted_role": "ola_migrator"},
        {**allowed[0], "member": "untrusted_role", "granted_role": "ola_migrator"},
        {**allowed[0], "granted_role": "unrelated_role"},
    ]
    for membership in unsafe_variants:
        assert validator(
            [membership], runtime_role="ola_runtime",
            worker_role="ola_worker", migration_role="ola_migrator",
        ), membership


def test_runtime_refuses_a_migration_dsn_but_migration_mode_can_use_it(monkeypatch):
    guard = getattr(database, "_assert_no_runtime_migration_url", None)
    assert callable(guard), "runtime migration-credential guard is missing"

    monkeypatch.delenv("OLA_DATABASE_MIGRATION_URL", raising=False)
    guard(enforce_runtime_privileges=True)

    monkeypatch.setenv(
        "OLA_DATABASE_MIGRATION_URL",
        "postgresql://migration.invalid/disabled-test-value",
    )
    with pytest.raises(RuntimeError, match="migration URL must not be available"):
        guard(enforce_runtime_privileges=True)

    guard(enforce_runtime_privileges=False)

    monkeypatch.setenv("OLA_DATABASE_MIGRATION_URL", "   ")
    guard(enforce_runtime_privileges=True)


def test_postgres_verifier_rejects_role_name_collisions_before_database_access():
    class UnreachableEngine:
        def connect(self):
            raise AssertionError("invalid role configuration must fail before connecting")

    with pytest.raises(RuntimeError, match="must be distinct"):
        database.verify_postgres_schema(
            UnreachableEngine(),
            runtime_role="ola_runtime",
            worker_role="ola_worker",
            migration_role="ola_runtime",
        )


def test_database_auth_context_rejects_malformed_evidence():
    import pytest
    from app.tenant_context import (
        set_api_key_context, set_worker_claim_context, set_checkout_context,
        set_database_auth_context,
    )

    with pytest.raises(ValueError, match="64-character lowercase hex"):
        set_api_key_context("not-a-fingerprint")
    with pytest.raises(ValueError, match="bounded lease"):
        set_worker_claim_context("job-1", "short", 0)
    with pytest.raises(ValueError, match="sandbox session id"):
        set_checkout_context("order-1", "cs_live_not-accepted")
    with pytest.raises(ValueError, match="unsupported"):
        set_database_auth_context("caller_supplied_tenant", "tenant-a")
