"""Tests for applying the tenant RLS context before signed worker reads."""

from types import SimpleNamespace
import uuid

import pytest

from app import signed_approval_runtime
from app.models import HumanGateMembership


def test_signed_worker_sets_verified_tenant_scope_before_membership_pk_lookup(monkeypatch):
    tenant_id = str(uuid.uuid4())
    principal_id = str(uuid.uuid4())
    actor = {
        "principal_id": principal_id,
        "tenant_id": tenant_id,
        "issuer": "https://issuer.example.test/tenant",
        "subject_fingerprint": "a" * 64,
        "fingerprint_key_id": "identity-k1",
        "role": "execution_approver",
        "membership_version": 7,
    }
    row = SimpleNamespace(
        id=principal_id,
        tenant_id=tenant_id,
        issuer=actor["issuer"],
        subject_fingerprint=actor["subject_fingerprint"],
        fingerprint_key_id=actor["fingerprint_key_id"],
        role="execution_approver",
        membership_version=7,
        active=True,
        revoked_at=None,
    )
    calls = []

    def set_scope(db, requested_tenant):
        calls.append(("scope", requested_tenant))

    class FakeSession:
        def get(self, model, key):
            calls.append(("get", key))
            assert model is HumanGateMembership
            return row

    monkeypatch.setattr(
        signed_approval_runtime, "set_human_gate_tenant_scope", set_scope,
    )
    resolved = signed_approval_runtime._current_membership(
        FakeSession(),
        actor,
        expected_tenant=tenant_id,
        expected_role="execution_approver",
        label="reviewer",
    )

    assert resolved is row
    assert calls == [("scope", tenant_id), ("get", principal_id)]


def test_signed_worker_never_reads_membership_when_tenant_scope_fails(monkeypatch):
    tenant_id = str(uuid.uuid4())
    principal_id = str(uuid.uuid4())
    actor = {
        "principal_id": principal_id,
        "tenant_id": tenant_id,
        "issuer": "https://issuer.example.test/tenant",
        "subject_fingerprint": "a" * 64,
        "fingerprint_key_id": "identity-k1",
        "role": "execution_approver",
        "membership_version": 1,
    }
    lookups = []

    def fail_scope(_db, _tenant):
        raise RuntimeError("tenant RLS scope unavailable")

    class FakeSession:
        def get(self, _model, key):
            lookups.append(key)
            return None

    monkeypatch.setattr(
        signed_approval_runtime, "set_human_gate_tenant_scope", fail_scope,
    )
    with pytest.raises(RuntimeError, match="tenant RLS scope unavailable"):
        signed_approval_runtime._current_membership(
            FakeSession(),
            actor,
            expected_tenant=tenant_id,
            expected_role="execution_approver",
            label="reviewer",
        )

    assert lookups == []


def test_human_gate_scope_rejects_switching_tenant_inside_transaction():
    from app.database import set_human_gate_tenant_scope

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    statements = []

    class FakeResult:
        def scalar_one_or_none(self):
            return tenant_a

    class FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def get_bind(self):
            return self.bind

        def execute(self, statement, params=None):
            sql = str(statement)
            statements.append((sql, params))
            return FakeResult()

    with pytest.raises(RuntimeError, match="cannot change within the same transaction"):
        set_human_gate_tenant_scope(FakeSession(), tenant_b)

    assert len(statements) == 1
    assert "current_setting('ola.human_gate_tenant_id'" in statements[0][0]
    assert all("set_config" not in sql for sql, _ in statements)


def test_human_gate_scope_allows_reapplying_same_tenant_inside_transaction():
    from app.database import set_human_gate_tenant_scope

    tenant = str(uuid.uuid4())
    statements = []

    class FakeResult:
        def scalar_one_or_none(self):
            return tenant

    class FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def get_bind(self):
            return self.bind

        def execute(self, statement, params=None):
            sql = str(statement)
            statements.append((sql, params))
            return FakeResult()

    set_human_gate_tenant_scope(FakeSession(), tenant)
    assert len(statements) == 2
    assert "set_config('ola.human_gate_tenant_id'" in statements[1][0]
