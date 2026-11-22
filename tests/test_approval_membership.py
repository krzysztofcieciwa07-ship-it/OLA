import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.approval_identity import VerifiedSubject
from app.approval_contract_v1 import oidc_subject_fingerprint
from app.approval_membership import (
    HumanGateMembershipError,
    resolve_human_gate_membership,
)
from app.database import Base
from app.models import HumanGateMembership, Tenant

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ISSUER = "https://login.example.test/tenant"
SUBJECT = "subject-123"
KEY = b"fingerprint-test-key-32-bytes-minimum"
KEY_ID = "identity-k1"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=TENANT, name="test-tenant"))
        session.commit()
        yield session
    engine.dispose()


def verified(tenant_id=TENANT):
    return VerifiedSubject(ISSUER, SUBJECT, tenant_id)


def seed_membership(db, *, role="execution_approver", active=True, revoked_at=None, version=1):
    fingerprint = oidc_subject_fingerprint(KEY, KEY_ID, TENANT, ISSUER, SUBJECT)
    row = HumanGateMembership(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        issuer=ISSUER,
        subject_fingerprint=fingerprint["value"],
        fingerprint_key_id=KEY_ID,
        role=role,
        membership_version=version,
        active=active,
        revoked_at=revoked_at,
    )
    db.add(row)
    db.commit()
    return row


def test_resolves_current_tenant_membership_and_role(db):
    row = seed_membership(db)
    result = resolve_human_gate_membership(
        db, verified(), resource_tenant_id=TENANT,
        fingerprint_key=KEY, fingerprint_key_id=KEY_ID,
        required_role="execution_approver",
    )
    assert result.principal_id == row.id
    assert result.tenant_id == TENANT
    assert result.role == "execution_approver"
    assert result.membership_version == 1
    assert result.subject_fingerprint == row.subject_fingerprint
    assert SUBJECT not in row.subject_fingerprint


def test_token_tenant_claim_must_match_resource_tenant(db):
    seed_membership(db)
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    with pytest.raises(HumanGateMembershipError, match="does not match"):
        resolve_human_gate_membership(
            db, verified(other), resource_tenant_id=TENANT,
            fingerprint_key=KEY, fingerprint_key_id=KEY_ID,
        )


def test_missing_membership_fails_closed(db):
    with pytest.raises(HumanGateMembershipError, match="missing or ambiguous"):
        resolve_human_gate_membership(
            db, verified(), resource_tenant_id=TENANT,
            fingerprint_key=KEY, fingerprint_key_id=KEY_ID,
        )


def test_role_mismatch_fails_closed(db):
    seed_membership(db, role="requester")
    with pytest.raises(HumanGateMembershipError, match="role does not authorize"):
        resolve_human_gate_membership(
            db, verified(), resource_tenant_id=TENANT,
            fingerprint_key=KEY, fingerprint_key_id=KEY_ID,
            required_role="execution_approver",
        )


def test_revoked_membership_fails_closed(db):
    seed_membership(db, active=False, revoked_at=1730000000)
    with pytest.raises(HumanGateMembershipError, match="inactive or invalid"):
        resolve_human_gate_membership(
            db, verified(), resource_tenant_id=TENANT,
            fingerprint_key=KEY, fingerprint_key_id=KEY_ID,
        )


def test_invalid_required_role_fails_closed(db):
    seed_membership(db)
    with pytest.raises(HumanGateMembershipError, match="required membership role"):
        resolve_human_gate_membership(
            db, verified(), resource_tenant_id=TENANT,
            fingerprint_key=KEY, fingerprint_key_id=KEY_ID,
            required_role="admin",
        )


def test_fingerprint_key_id_is_bound_to_membership(db):
    seed_membership(db)
    with pytest.raises(HumanGateMembershipError, match="missing or ambiguous"):
        resolve_human_gate_membership(
            db, verified(), resource_tenant_id=TENANT,
            fingerprint_key=KEY, fingerprint_key_id="identity-k2",
        )


def test_raw_subject_is_not_a_membership_column(db):
    row = seed_membership(db)
    columns = {column.name for column in HumanGateMembership.__table__.columns}
    assert "subject" not in columns
    assert row.subject_fingerprint != SUBJECT
