"""Tenant-scoped resolver for verified OIDC Human Gate identities.

This module does not authenticate tokens, grant memberships, or authorize an
external effect. Call verify_subject_token() first, then resolve the subject
against OLA-owned membership state for the exact resource tenant.
"""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy import select

from .approval_identity import VerifiedSubject
from .approval_contract_v1 import oidc_subject_fingerprint
from .database import set_human_gate_tenant_scope
from .models import HumanGateMembership

ALLOWED_MEMBERSHIP_ROLES = frozenset({
    "requester", "execution_approver", "report_reviewer",
})


class HumanGateMembershipError(ValueError):
    """Verified identity could not be mapped to a current tenant membership."""


@dataclass(frozen=True)
class ResolvedMembership:
    principal_id: str
    tenant_id: str
    issuer: str
    subject_fingerprint: str
    fingerprint_key_id: str
    role: str
    membership_version: int


def _canonical_uuid(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise HumanGateMembershipError(f"{name} must be a canonical UUID")
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise HumanGateMembershipError(f"{name} must be a canonical UUID") from None
    if value != normalized:
        raise HumanGateMembershipError(f"{name} must be a canonical UUID")
    return normalized


def resolve_human_gate_membership(
    db,
    verified_subject: VerifiedSubject,
    *,
    resource_tenant_id: str,
    fingerprint_key: bytes,
    fingerprint_key_id: str,
    required_role: str,
) -> ResolvedMembership:
    """Resolve the verified (issuer, subject) to one active OLA membership.

    The token's tenant claim must match the exact resource tenant, but the claim
    is not itself role authority. The role and membership version are loaded
    from the OLA-owned database row. No raw subject or token is persisted.
    """
    if not isinstance(verified_subject, VerifiedSubject):
        raise HumanGateMembershipError("OIDC identity must come from the verifier")
    tenant_id = _canonical_uuid(resource_tenant_id, "resource_tenant_id")
    token_tenant_id = _canonical_uuid(verified_subject.tenant_id, "verified tenant claim")
    if token_tenant_id != tenant_id:
        raise HumanGateMembershipError("verified tenant claim does not match the resource tenant")
    if required_role not in ALLOWED_MEMBERSHIP_ROLES:
        raise HumanGateMembershipError("required membership role is invalid")

    try:
        fingerprint = oidc_subject_fingerprint(
            fingerprint_key,
            fingerprint_key_id,
            tenant_id,
            verified_subject.issuer,
            verified_subject.subject,
        )
    except (ValueError, TypeError):
        raise HumanGateMembershipError("verified subject fingerprint input is invalid") from None

    # PostgreSQL RLS scopes the complete transaction; the explicit predicate
    # remains as a second, application-level tenant binding.
    try:
        set_human_gate_tenant_scope(db, tenant_id)
    except (ValueError, RuntimeError):
        raise HumanGateMembershipError("tenant RLS scope could not be established") from None

    rows = db.scalars(select(HumanGateMembership).where(
        HumanGateMembership.tenant_id == tenant_id,
        HumanGateMembership.issuer == verified_subject.issuer,
        HumanGateMembership.fingerprint_key_id == fingerprint["key_id"],
        HumanGateMembership.subject_fingerprint == fingerprint["value"],
    )).all()
    if len(rows) != 1:
        raise HumanGateMembershipError("current tenant membership is missing or ambiguous")

    row = rows[0]
    if (
        row.tenant_id != tenant_id
        or row.active is not True
        or row.revoked_at is not None
        or not isinstance(row.membership_version, int)
        or isinstance(row.membership_version, bool)
        or row.membership_version < 1
        or row.role not in ALLOWED_MEMBERSHIP_ROLES
    ):
        raise HumanGateMembershipError("tenant membership is inactive or invalid")
    if row.role != required_role:
        raise HumanGateMembershipError("tenant membership role does not authorize this action")

    principal_id = _canonical_uuid(row.id, "principal_id")
    return ResolvedMembership(
        principal_id=principal_id,
        tenant_id=tenant_id,
        issuer=row.issuer,
        subject_fingerprint=row.subject_fingerprint,
        fingerprint_key_id=row.fingerprint_key_id,
        role=row.role,
        membership_version=row.membership_version,
    )
