"""HR-backed person identity, dual-control roles and API-key owner SoD tests."""
import importlib
from importlib.util import find_spec
import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.hashchain import verify_chain
from app.models import ApiKey, EvidenceRecord, HumanPrincipal, Tenant


def test_human_membership_module_exists():
    assert find_spec("app.human_identity.membership") is not None, (
        "HR-backed SoD and membership governance module is missing"
    )


@pytest.fixture
def membership_api():
    if find_spec("app.human_identity.membership") is None:
        pytest.skip("HR-backed SoD module has not been implemented")
    return importlib.import_module("app.human_identity.membership")


@pytest.fixture
def identity_pepper(monkeypatch):
    monkeypatch.setenv("OLA_PERSON_KEY_PEPPER", "test-only-HR-person-key-pepper-32-bytes-min")


def _tenant():
    from app.human_identity.policy import set_tenant_human_gate_mode

    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="human-sod-test"))
        db.commit()
    set_tenant_human_gate_mode(
        tenant_id=tenant_id,
        actor_ref="bootstrap-principal-owner",
        reason="Enable OIDC for isolated Human SoD contract test",
        target_mode="OIDC_REQUIRED",
    )
    return tenant_id


def _principal(tenant_id, subject):
    principal_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(HumanPrincipal(
            id=principal_id,
            tenant_id=tenant_id,
            issuer="https://trusted-idp.example.test",
            subject=subject,
            status="ACTIVE",
        ))
        db.commit()
    return principal_id


def _set_admin_role(tenant_id, principal_id, membership_role_model):
    with SessionLocal() as db:
        db.add(membership_role_model(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            principal_id=principal_id,
            role="tenant_identity_admin",
            status="ACTIVE",
            created_by_ref="principal-bootstrap-owner",
        ))
        db.commit()


def _records(tenant_id):
    with SessionLocal() as db:
        rows = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.asc())
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


def test_two_oidc_accounts_for_one_hr_person_share_the_same_pseudonymous_ref(
    membership_api, identity_pepper
):
    tenant_id = _tenant()
    first = _principal(tenant_id, "oidc-account-A")
    second = _principal(tenant_id, "oidc-account-B")
    raw_hr_key = "hr-fixture-person-001"

    first_result = membership_api.bind_principal_to_person(
        tenant_id=tenant_id,
        principal_id=first,
        person_key=raw_hr_key,
        source="HR_SCIM",
        actor_ref="principal-provisioner-1",
        reason="SCIM identity sync",
    )
    second_result = membership_api.bind_principal_to_person(
        tenant_id=tenant_id,
        principal_id=second,
        person_key=raw_hr_key,
        source="HR_SCIM",
        actor_ref="principal-provisioner-1",
        reason="SCIM identity sync for second IdP account",
    )

    assert first_result["person_ref"] == second_result["person_ref"]
    assert raw_hr_key not in str(first_result)
    records = _records(tenant_id)
    binding_records = [
        row for row in records
        if row["record_type"] == "human.person_identity_bound"
    ]
    assert len(binding_records) == 2
    assert all(raw_hr_key not in row["payload_json"] for row in records)
    assert verify_chain(records)[0] is True


def test_distinct_person_check_rejects_alias_accounts_of_same_person(membership_api):
    with pytest.raises(membership_api.HumanMembershipRejected) as error:
        membership_api.assert_distinct_humans(
            "person-ref-same-human",
            "person-ref-same-human",
            "person-ref-third-human",
        )
    assert error.value.code == 403


def test_privileged_role_requires_a_second_distinct_human_admin(
    membership_api, identity_pepper
):
    tenant_id = _tenant()
    admin_one = _principal(tenant_id, "admin-one")
    admin_two = _principal(tenant_id, "admin-two")
    target = _principal(tenant_id, "reviewer-target")
    for principal_id, key in (
        (admin_one, "HR-ADMIN-001"),
        (admin_two, "HR-ADMIN-002"),
        (target, "HR-REVIEWER-003"),
    ):
        membership_api.bind_principal_to_person(
            tenant_id=tenant_id,
            principal_id=principal_id,
            person_key=key,
            source="HR_SCIM",
            actor_ref="principal-provisioner",
            reason="verified HR mapping",
        )
    role_model = importlib.import_module("app.models").HumanMembershipRole
    _set_admin_role(tenant_id, admin_one, role_model)
    _set_admin_role(tenant_id, admin_two, role_model)

    request = membership_api.request_role_change(
        tenant_id=tenant_id,
        requester_principal_id=admin_one,
        target_principal_id=target,
        requested_role="report_reviewer",
        operation="GRANT",
        reason="Assign independent report review responsibility",
    )
    with pytest.raises(membership_api.HumanMembershipRejected) as self_approval:
        membership_api.approve_role_change(
            tenant_id=tenant_id,
            change_id=request["change_id"],
            approver_principal_id=admin_one,
            reason="same administrator cannot approve",
        )
    assert self_approval.value.code == 403

    approved = membership_api.approve_role_change(
        tenant_id=tenant_id,
        change_id=request["change_id"],
        approver_principal_id=admin_two,
        reason="Independent dual-control approval",
    )
    assert approved["status"] == "APPROVED"
    with SessionLocal() as db:
        role = db.scalar(select(role_model).where(
            role_model.tenant_id == tenant_id,
            role_model.principal_id == target,
            role_model.role == "report_reviewer",
        ))
        assert role is not None and role.status == "ACTIVE"


def test_role_change_cannot_self_grant_or_use_unknown_role(
    membership_api, identity_pepper
):
    tenant_id = _tenant()
    admin = _principal(tenant_id, "admin-self")
    membership_api.bind_principal_to_person(
        tenant_id=tenant_id,
        principal_id=admin,
        person_key="HR-ADMIN-SELF",
        source="HR_SCIM",
        actor_ref="principal-provisioner",
        reason="verified HR mapping",
    )
    role_model = importlib.import_module("app.models").HumanMembershipRole
    _set_admin_role(tenant_id, admin, role_model)

    with pytest.raises(membership_api.HumanMembershipRejected) as self_grant:
        membership_api.request_role_change(
            tenant_id=tenant_id,
            requester_principal_id=admin,
            target_principal_id=admin,
            requested_role="report_reviewer",
            operation="GRANT",
            reason="attempt self grant",
        )
    assert self_grant.value.code == 403

    other = _principal(tenant_id, "another-account")
    membership_api.bind_principal_to_person(
        tenant_id=tenant_id,
        principal_id=other,
        person_key="HR-OTHER-001",
        source="HR_SCIM",
        actor_ref="principal-provisioner",
        reason="verified HR mapping",
    )
    with pytest.raises(membership_api.HumanMembershipRejected) as unknown_role:
        membership_api.request_role_change(
            tenant_id=tenant_id,
            requester_principal_id=admin,
            target_principal_id=other,
            requested_role="superuser",
            operation="GRANT",
            reason="unknown role must fail",
        )
    assert unknown_role.value.code == 400


def test_api_key_owner_mapping_requires_dual_control_and_is_pseudonymous(
    membership_api, identity_pepper
):
    tenant_id = _tenant()
    admin_one = _principal(tenant_id, "owner-admin-one")
    admin_two = _principal(tenant_id, "owner-admin-two")
    owner = _principal(tenant_id, "api-key-owner")
    for principal_id, key in (
        (admin_one, "HR-OWNER-ADMIN-001"),
        (admin_two, "HR-OWNER-ADMIN-002"),
        (owner, "HR-API-OWNER-003"),
    ):
        membership_api.bind_principal_to_person(
            tenant_id=tenant_id,
            principal_id=principal_id,
            person_key=key,
            source="HR_SCIM",
            actor_ref="principal-provisioner",
            reason="verified HR mapping",
        )
    role_model = importlib.import_module("app.models").HumanMembershipRole
    _set_admin_role(tenant_id, admin_one, role_model)
    _set_admin_role(tenant_id, admin_two, role_model)
    key_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(ApiKey(
            id=key_id,
            tenant_id=tenant_id,
            key_hash=("a" * 64),
            role="tenant",
        ))
        db.commit()

    result = membership_api.assign_api_key_owner(
        tenant_id=tenant_id,
        api_key_id=key_id,
        owner_principal_id=owner,
        requester_principal_id=admin_one,
        approver_principal_id=admin_two,
        reason="bind service key to accountable HR owner",
    )
    assert result["status"] == "OWNER_BOUND"
    assert result["owner_person_ref"]
    with SessionLocal() as db:
        api_key = db.get(ApiKey, key_id)
        assert api_key.owner_person_ref == result["owner_person_ref"]

    records = _records(tenant_id)
    assert any(row["record_type"] == "human.api_key_owner_bound" for row in records)
    assert "HR-API-OWNER-003" not in "".join(row["payload_json"] for row in records)
    assert verify_chain(records)[0] is True
