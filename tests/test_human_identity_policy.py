"""Behavioral tests for the persistent, downgrade-resistant Human Gate policy."""
import importlib
import uuid

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal, engine
from app.hashchain import verify_chain


def _policy_api():
    module = importlib.import_module("app.human_identity.policy")
    setter = getattr(module, "set_tenant_human_gate_mode", None)
    resolver = getattr(module, "require_human_identity_mode", None)
    rejected = getattr(module, "HumanIdentityPolicyRejected", None)
    assert callable(setter), "persistent policy setter is missing"
    assert callable(resolver), "production policy resolver is missing"
    assert isinstance(rejected, type) and issubclass(rejected, Exception), (
        "policy rejection type is missing"
    )

    from app import models
    tenant_model = getattr(models, "Tenant", None)
    evidence_model = getattr(models, "EvidenceRecord", None)
    policy_model = getattr(models, "TenantIdentityPolicy", None)
    assert tenant_model is not None, "tenant model is missing"
    assert evidence_model is not None, "EvidenceRecord model is missing"
    assert policy_model is not None, "persistent tenant identity policy model is missing"
    return setter, resolver, rejected, tenant_model, evidence_model, policy_model


def _tenant(tenant_model):
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(tenant_model(id=tenant_id, name="human-identity-policy-test"))
        db.commit()
    return tenant_id


def _records(evidence_model, tenant_id):
    with SessionLocal() as db:
        rows = db.scalars(
            select(evidence_model)
            .where(evidence_model.tenant_id == tenant_id)
            .order_by(evidence_model.seq.asc())
        ).all()
        return [{
            "id": row.id,
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "record_type": row.record_type,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
            "payload_json": row.payload_json,
        } for row in rows]


def test_legacy_sandbox_is_explicit_but_production_fails_closed_without_oidc():
    _setter, resolver, rejected, tenant_model, _evidence_model, _policy_model = _policy_api()
    tenant_id = _tenant(tenant_model)

    assert resolver(tenant_id=tenant_id, deployment_profile="sandbox") == "LEGACY_API"
    with pytest.raises(rejected) as error:
        resolver(tenant_id=tenant_id, deployment_profile="production")
    assert error.value.code == 403


def test_oidc_upgrade_is_durable_and_appends_pseudonymous_evidence():
    setter, resolver, _rejected, tenant_model, evidence_model, policy_model = _policy_api()
    tenant_id = _tenant(tenant_model)

    result = setter(
        tenant_id=tenant_id,
        actor_ref="principal-ref-operator-7",
        reason="Enable verified operator identity before controlled use",
        target_mode="OIDC_REQUIRED",
    )

    assert result["status"] == "OIDC_REQUIRED"
    assert resolver(tenant_id=tenant_id, deployment_profile="production") == "OIDC_REQUIRED"
    with SessionLocal() as db:
        policy = db.get(policy_model, tenant_id)
        assert policy is not None
        assert policy.human_gate_mode == "OIDC_REQUIRED"
        assert policy.changed_by_ref == "principal-ref-operator-7"

    records = _records(evidence_model, tenant_id)
    assert len(records) == 1
    assert records[0]["record_type"] == "human.identity_policy_enabled"
    assert verify_chain(records)[0] is True
    assert "principal-ref-operator-7" in records[0]["payload_json"]
    for private_claim in ("issuer", "subject", "email"):
        assert private_claim not in records[0]["payload_json"].lower()


def test_repeated_oidc_upgrade_is_idempotent_and_does_not_duplicate_evidence():
    setter, _resolver, _rejected, tenant_model, evidence_model, _policy_model = _policy_api()
    tenant_id = _tenant(tenant_model)
    first = setter(
        tenant_id=tenant_id,
        actor_ref="principal-ref-admin-1",
        reason="Enable OIDC",
        target_mode="OIDC_REQUIRED",
    )
    second = setter(
        tenant_id=tenant_id,
        actor_ref="principal-ref-admin-1",
        reason="Retry the same policy request",
        target_mode="OIDC_REQUIRED",
    )

    assert first["status"] == "OIDC_REQUIRED"
    assert second["status"] == "OIDC_REQUIRED"
    assert second["changed"] is False
    records = _records(evidence_model, tenant_id)
    assert len(records) == 1
    assert verify_chain(records)[0] is True


def test_downgrade_attempt_is_blocked_audited_and_never_changes_policy():
    setter, resolver, rejected, tenant_model, evidence_model, policy_model = _policy_api()
    tenant_id = _tenant(tenant_model)
    setter(
        tenant_id=tenant_id,
        actor_ref="principal-ref-admin-1",
        reason="Enable OIDC",
        target_mode="OIDC_REQUIRED",
    )

    with pytest.raises(rejected) as error:
        setter(
            tenant_id=tenant_id,
            actor_ref="principal-ref-admin-2",
            reason="Attempt downgrade to API key",
            target_mode="LEGACY_API",
        )
    assert error.value.code == 409
    assert resolver(tenant_id=tenant_id, deployment_profile="production") == "OIDC_REQUIRED"
    with SessionLocal() as db:
        policy = db.get(policy_model, tenant_id)
        assert policy.human_gate_mode == "OIDC_REQUIRED"

    records = _records(evidence_model, tenant_id)
    assert [row["record_type"] for row in records] == [
        "human.identity_policy_enabled",
        "human.identity_policy_downgrade_blocked",
    ]
    assert verify_chain(records)[0] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actor_ref": "", "reason": "valid reason", "target_mode": "OIDC_REQUIRED"},
        {"actor_ref": "principal-ref", "reason": "", "target_mode": "OIDC_REQUIRED"},
        {"actor_ref": "person@example.com", "reason": "valid reason", "target_mode": "OIDC_REQUIRED"},
        {"actor_ref": "principal-ref", "reason": "valid reason", "target_mode": "UNKNOWN"},
    ],
)
def test_invalid_actor_reason_or_target_mode_is_rejected(kwargs):
    setter, _resolver, rejected, tenant_model, _evidence_model, _policy_model = _policy_api()
    tenant_id = _tenant(tenant_model)

    with pytest.raises(rejected) as error:
        setter(tenant_id=tenant_id, **kwargs)
    assert error.value.code == 400


def test_enabled_oidc_policy_cannot_be_downgraded_or_deleted_by_direct_database_write():
    setter, _resolver, _rejected, tenant_model, _evidence_model, policy_model = _policy_api()
    tenant_id = _tenant(tenant_model)
    setter(
        tenant_id=tenant_id,
        actor_ref="principal-ref-admin-db",
        reason="Enable OIDC before direct database tamper test",
        target_mode="OIDC_REQUIRED",
    )

    table = policy_model.__table__
    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                update(table)
                .where(table.c.tenant_id == tenant_id)
                .values(human_gate_mode="LEGACY_API")
            )

    with pytest.raises(SQLAlchemyError):
        with engine.begin() as connection:
            connection.execute(
                delete(table).where(table.c.tenant_id == tenant_id)
            )
