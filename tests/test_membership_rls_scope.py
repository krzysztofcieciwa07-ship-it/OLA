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
