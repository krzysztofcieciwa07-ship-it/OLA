"""HR-backed person identity, tenant role membership and dual-control SoD."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.database import SessionLocal, begin_write_transaction
from app.hashchain import (
    GENESIS_HASH,
    compute_record_hash_v2,
    sealed_payload_json,
)
from app.models import (
    ApiKey,
    EvidenceRecord,
    HumanMembershipRole,
    HumanPrincipal,
    HumanRoleChangeRequest,
    Tenant,
    TenantIdentityPolicy,
)


ALLOWED_PERSON_KEY_SOURCES = frozenset({"HR_SCIM", "TRUSTED_IDP_CLAIM"})
ALLOWED_ROLES = frozenset({
    "tenant_identity_admin",
    "execution_approver",
    "report_reviewer",
    "recipient",
})
ALLOWED_OPERATIONS = frozenset({"GRANT", "REVOKE"})
ACTOR_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,127}$")


class HumanMembershipRejected(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HumanPrincipalContext:
    tenant_id: str
    principal_id: str
    principal_ref: str
    person_ref: str
    roles: frozenset[str]
    auth_time: int | None
    mfa_verified: bool


def _actor_ref(value: str) -> str:
    if not isinstance(value, str) or ACTOR_REF_RE.fullmatch(value.strip()) is None:
        raise HumanMembershipRejected(400, "actor_ref must be a pseudonymous principal reference")
    return value.strip()


def _required_reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HumanMembershipRejected(400, "a nonempty reason is required")
    if len(value.strip()) > 1000:
        raise HumanMembershipRejected(400, "reason exceeds 1000 characters")
    return value.strip()


def _person_key_pepper() -> bytes:
    raw = os.environ.get("OLA_PERSON_KEY_PEPPER")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) < 32:
        raise HumanMembershipRejected(
            503, "HR person-key pseudonymization secret is unavailable"
        )
    return raw.encode("utf-8")


def person_ref_for_key(*, tenant_id: str, person_key: str, source: str) -> str:
    """Return a stable tenant-scoped HMAC pseudonym without persisting raw HR key."""
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HumanMembershipRejected(400, "tenant_id is required")
    if not isinstance(person_key, str) or not 3 <= len(person_key.strip()) <= 256:
        raise HumanMembershipRejected(400, "HR person_key must contain 3 to 256 characters")
    if source not in ALLOWED_PERSON_KEY_SOURCES:
        raise HumanMembershipRejected(400, "untrusted HR person-key source")
    material = (
        b"OLA-HUMAN-PERSON-REF-V1\x00"
        + tenant_id.encode("utf-8")
        + b"\x00"
        + person_key.strip().encode("utf-8")
    )
    return hmac.new(_person_key_pepper(), material, hashlib.sha256).hexdigest()


def _append_evidence_locked(db, tenant_id: str, record_type: str, payload: dict) -> dict:
    latest = db.scalar(
        select(EvidenceRecord)
        .where(EvidenceRecord.tenant_id == tenant_id)
        .order_by(EvidenceRecord.seq.desc())
        .limit(1)
    )
    seq = latest.seq + 1 if latest is not None else 0
    previous_hash = latest.record_hash if latest is not None else GENESIS_HASH
    payload_json = sealed_payload_json(record_type, payload, producer="ola_runtime")
    digest = compute_record_hash_v2(
        tenant_id, seq, previous_hash, record_type, "ola_runtime", payload_json,
    )
    record_id = str(uuid.uuid4())
    db.add(EvidenceRecord(
        id=record_id,
        tenant_id=tenant_id,
        seq=seq,
        record_type=record_type,
        payload_json=payload_json,
        prev_hash=previous_hash,
        record_hash=digest,
    ))
    db.flush()
    return {"id": record_id, "seq": seq, "record_hash": digest}


def _require_oidc_required(db, tenant_id: str) -> None:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HumanMembershipRejected(404, "tenant not found")
    policy = db.get(TenantIdentityPolicy, tenant_id)
    if policy is None or policy.human_gate_mode != "OIDC_REQUIRED":
        raise HumanMembershipRejected(
            403, "HR-backed human membership changes require persistent OIDC_REQUIRED policy"
        )


def _principal(db, tenant_id: str, principal_id: str) -> HumanPrincipal:
    principal = db.scalar(select(HumanPrincipal).where(
        HumanPrincipal.id == principal_id,
        HumanPrincipal.tenant_id == tenant_id,
    ).with_for_update())
    if principal is None or principal.status != "ACTIVE":
        raise HumanMembershipRejected(404, "active tenant human principal not found")
    if not principal.person_ref:
        raise HumanMembershipRejected(
            403, "human principal has no verified HR-backed person mapping"
        )
    return principal


def _require_role(db, tenant_id: str, principal_id: str, role: str) -> HumanPrincipal:
    principal = _principal(db, tenant_id, principal_id)
    membership = db.scalar(select(HumanMembershipRole).where(
        HumanMembershipRole.tenant_id == tenant_id,
        HumanMembershipRole.principal_id == principal_id,
        HumanMembershipRole.role == role,
        HumanMembershipRole.status == "ACTIVE",
    ))
    if membership is None:
        raise HumanMembershipRejected(403, f"active {role} membership is required")
    return principal


def _principal_ref(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return value.get("person_ref")
    return getattr(value, "person_ref", None)


def assert_distinct_humans(*person_refs) -> None:
    """Fail closed unless every input is a verified, unique HR-backed person ref."""
    if len(person_refs) < 2:
        raise HumanMembershipRejected(400, "at least two human person references are required")
    refs = [_principal_ref(item) for item in person_refs]
    if any(not isinstance(ref, str) or not ref for ref in refs):
        raise HumanMembershipRejected(403, "HR-backed person identity is missing")
    if len(set(refs)) != len(refs):
        raise HumanMembershipRejected(403, "SoD violation: the same human cannot fill multiple roles")


def bind_principal_to_person(
    *,
    tenant_id: str,
    principal_id: str,
    person_key: str,
    source: str,
    actor_ref: str,
    reason: str,
) -> dict:
    """Bind an existing OIDC account to a trusted HR person pseudonym.

    Rebinding an already-associated account to another person is forbidden.
    The raw person_key is used only in memory to derive the HMAC and is never
    written to a table, Evidence payload, response, or application log.
    """
    actor_ref = _actor_ref(actor_ref)
    reason = _required_reason(reason)
    person_ref = person_ref_for_key(
        tenant_id=tenant_id, person_key=person_key, source=source,
    )

    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_required(db, tenant_id)
        principal = db.scalar(select(HumanPrincipal).where(
            HumanPrincipal.id == principal_id,
            HumanPrincipal.tenant_id == tenant_id,
        ).with_for_update())
        if principal is None or principal.status != "ACTIVE":
            raise HumanMembershipRejected(404, "active tenant human principal not found")
        if principal.person_ref:
            if hmac.compare_digest(principal.person_ref, person_ref):
                db.rollback()
                return {
                    "status": "ALREADY_BOUND",
                    "tenant_id": tenant_id,
                    "principal_id": principal_id,
                    "person_ref": person_ref,
                }
            raise HumanMembershipRejected(
                409, "human principal is already bound to another HR person; controlled identity reconciliation required"
            )
        principal.person_ref = person_ref
        principal.person_key_source = source
        principal.person_bound_at = int(time.time())
        evidence = _append_evidence_locked(
            db, tenant_id, "human.person_identity_bound", {
                "tenant_id": tenant_id,
                "principal_id": principal_id,
                "person_ref": person_ref,
                "source": source,
                "actor_ref": actor_ref,
                "reason": reason,
                "decision": "PERSON_BOUND",
                "bound_at": principal.person_bound_at,
            },
        )
        db.commit()

    return {
        "status": "PERSON_BOUND",
        "tenant_id": tenant_id,
        "principal_id": principal_id,
        "person_ref": person_ref,
        "evidence_id": evidence["id"],
    }


def request_role_change(
    *,
    tenant_id: str,
    requester_principal_id: str,
    target_principal_id: str,
    requested_role: str,
    operation: str,
    reason: str,
) -> dict:
    reason = _required_reason(reason)
    if requested_role not in ALLOWED_ROLES:
        raise HumanMembershipRejected(400, "requested role is not allowed")
    if operation not in ALLOWED_OPERATIONS:
        raise HumanMembershipRejected(400, "role operation must be GRANT or REVOKE")
    if not all(isinstance(value, str) and value for value in (
        tenant_id, requester_principal_id, target_principal_id,
    )):
        raise HumanMembershipRejected(400, "tenant and principal identifiers are required")

    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_required(db, tenant_id)
        requester = _require_role(
            db, tenant_id, requester_principal_id, "tenant_identity_admin",
        )
        target = _principal(db, tenant_id, target_principal_id)
        assert_distinct_humans(requester.person_ref, target.person_ref)
        existing = db.scalar(select(HumanRoleChangeRequest).where(
            HumanRoleChangeRequest.tenant_id == tenant_id,
            HumanRoleChangeRequest.target_principal_id == target_principal_id,
            HumanRoleChangeRequest.requested_role == requested_role,
            HumanRoleChangeRequest.operation == operation,
            HumanRoleChangeRequest.status == "PENDING",
        ).with_for_update())
        if existing is not None:
            raise HumanMembershipRejected(409, "an equivalent role change is already pending")

        change_id = str(uuid.uuid4())
        requested_at = int(time.time())
        change = HumanRoleChangeRequest(
            id=change_id,
            tenant_id=tenant_id,
            requester_principal_id=requester_principal_id,
            requester_person_ref=requester.person_ref,
            target_principal_id=target_principal_id,
            target_person_ref=target.person_ref,
            requested_role=requested_role,
            operation=operation,
            reason=reason,
            status="PENDING",
            requested_at=requested_at,
        )
        db.add(change)
        evidence = _append_evidence_locked(
            db, tenant_id, "human.role_change_requested", {
                "tenant_id": tenant_id,
                "change_id": change_id,
                "requester_principal_id": requester_principal_id,
                "requester_person_ref": requester.person_ref,
                "target_principal_id": target_principal_id,
                "target_person_ref": target.person_ref,
                "requested_role": requested_role,
                "operation": operation,
                "reason": reason,
                "decision": "PENDING",
                "requested_at": requested_at,
            },
        )
        change.request_evidence_id = evidence["id"]
        db.commit()

    return {
        "status": "PENDING",
        "change_id": change_id,
        "request_evidence_id": evidence["id"],
        "requested_role": requested_role,
        "operation": operation,
    }


def approve_role_change(
    *,
    tenant_id: str,
    change_id: str,
    approver_principal_id: str,
    reason: str,
) -> dict:
    reason = _required_reason(reason)
    if not all(isinstance(value, str) and value for value in (
        tenant_id, change_id, approver_principal_id,
    )):
        raise HumanMembershipRejected(400, "tenant, change and approver identifiers are required")

    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_required(db, tenant_id)
        approver = _require_role(
            db, tenant_id, approver_principal_id, "tenant_identity_admin",
        )
        change = db.scalar(select(HumanRoleChangeRequest).where(
            HumanRoleChangeRequest.id == change_id,
            HumanRoleChangeRequest.tenant_id == tenant_id,
        ).with_for_update())
        if change is None:
            raise HumanMembershipRejected(404, "role change request not found")
        if change.status != "PENDING":
            raise HumanMembershipRejected(409, "role change request is not pending")
        assert_distinct_humans(
            change.requester_person_ref,
            approver.person_ref,
            change.target_person_ref,
        )
        target = _principal(db, tenant_id, change.target_principal_id)
        if target.person_ref != change.target_person_ref:
            raise HumanMembershipRejected(409, "target HR person mapping changed after role request")

        role = db.scalar(select(HumanMembershipRole).where(
            HumanMembershipRole.tenant_id == tenant_id,
            HumanMembershipRole.principal_id == change.target_principal_id,
            HumanMembershipRole.role == change.requested_role,
        ).with_for_update())
        approved_at = int(time.time())
        if change.operation == "GRANT":
            if role is None:
                role = HumanMembershipRole(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    principal_id=change.target_principal_id,
                    role=change.requested_role,
                    status="ACTIVE",
                    created_by_ref=approver.id,
                    created_at=approved_at,
                )
                db.add(role)
            elif role.status != "ACTIVE":
                role.status = "ACTIVE"
                role.created_by_ref = approver.id
                role.created_at = approved_at
                role.revoked_at = None
        elif change.operation == "REVOKE":
            if role is None or role.status != "ACTIVE":
                raise HumanMembershipRejected(409, "role to revoke is not active")
            role.status = "REVOKED"
            role.revoked_at = approved_at
        else:
            raise HumanMembershipRejected(409, "stored role operation is invalid")

        change.status = "APPROVED"
        change.approver_principal_id = approver_principal_id
        change.approver_person_ref = approver.person_ref
        change.approved_at = approved_at
        evidence = _append_evidence_locked(
            db, tenant_id, "human.role_change_approved", {
                "tenant_id": tenant_id,
                "change_id": change_id,
                "requester_person_ref": change.requester_person_ref,
                "target_person_ref": change.target_person_ref,
                "approver_principal_id": approver_principal_id,
                "approver_person_ref": approver.person_ref,
                "requested_role": change.requested_role,
                "operation": change.operation,
                "reason": reason,
                "decision": "APPROVED",
                "approved_at": approved_at,
            },
        )
        change.approval_evidence_id = evidence["id"]
        result_target_principal_id = change.target_principal_id
        result_role = change.requested_role
        db.commit()

    return {
        "status": "APPROVED",
        "change_id": change_id,
        "approval_evidence_id": evidence["id"],
        "target_principal_id": result_target_principal_id,
        "role": result_role,
    }


def assign_api_key_owner(
    *,
    tenant_id: str,
    api_key_id: str,
    owner_principal_id: str,
    requester_principal_id: str,
    approver_principal_id: str,
    reason: str,
) -> dict:
    """Bind a machine API key to an accountable human owner with two-admin control."""
    reason = _required_reason(reason)
    if not all(isinstance(value, str) and value for value in (
        tenant_id, api_key_id, owner_principal_id,
        requester_principal_id, approver_principal_id,
    )):
        raise HumanMembershipRejected(400, "tenant, API key, owner, requester and approver are required")

    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_required(db, tenant_id)
        requester = _require_role(
            db, tenant_id, requester_principal_id, "tenant_identity_admin",
        )
        approver = _require_role(
            db, tenant_id, approver_principal_id, "tenant_identity_admin",
        )
        owner = _principal(db, tenant_id, owner_principal_id)
        assert_distinct_humans(requester.person_ref, approver.person_ref)
        if owner.person_ref in {requester.person_ref, approver.person_ref}:
            raise HumanMembershipRejected(403, "API key owner must be independent from both approving administrators")
        owner_person_ref = owner.person_ref

        api_key = db.scalar(select(ApiKey).where(
            ApiKey.id == api_key_id,
            ApiKey.tenant_id == tenant_id,
        ).with_for_update())
        if api_key is None:
            raise HumanMembershipRejected(404, "tenant API key not found")
        if api_key.owner_person_ref and api_key.owner_person_ref != owner.person_ref:
            raise HumanMembershipRejected(
                409, "API key already has an accountable owner; controlled ownership transfer is required"
            )
        api_key.owner_person_ref = owner.person_ref
        evidence = _append_evidence_locked(
            db, tenant_id, "human.api_key_owner_bound", {
                "tenant_id": tenant_id,
                "api_key_id": api_key_id,
                "owner_person_ref": owner_person_ref,
                "requester_person_ref": requester.person_ref,
                "approver_person_ref": approver.person_ref,
                "reason": reason,
                "decision": "OWNER_BOUND",
                "bound_at": int(time.time()),
            },
        )
        db.commit()

    return {
        "status": "OWNER_BOUND",
        "api_key_id": api_key_id,
        "owner_person_ref": owner_person_ref,
        "evidence_id": evidence["id"],
    }


def resolve_human_principal_context(
    *, tenant_id: str, principal_id: str, auth_time: int | None,
    mfa_verified: bool,
) -> HumanPrincipalContext:
    """Resolve a server-authenticated OIDC principal and its active tenant roles."""
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HumanMembershipRejected(400, "tenant_id is required")
    with SessionLocal() as db:
        _require_oidc_required(db, tenant_id)
        principal = _principal(db, tenant_id, principal_id)
        roles = frozenset(db.scalars(select(HumanMembershipRole.role).where(
            HumanMembershipRole.tenant_id == tenant_id,
            HumanMembershipRole.principal_id == principal_id,
            HumanMembershipRole.status == "ACTIVE",
        )).all())
        return HumanPrincipalContext(
            tenant_id=tenant_id,
            principal_id=principal_id,
            principal_ref=principal.id,
            person_ref=principal.person_ref,
            roles=roles,
            auth_time=auth_time,
            mfa_verified=bool(mfa_verified),
        )


def bootstrap_tenant_admin(
    *,
    tenant_id: str,
    principal_id: str,
    bootstrap_token: str,
    reason: str,
) -> dict:
    """Out-of-band first-admin bootstrap. There is deliberately no HTTP route."""
    configured = os.environ.get("OLA_HUMAN_IDENTITY_BOOTSTRAP_TOKEN", "")
    if (
        not isinstance(configured, str) or len(configured) < 32
        or not isinstance(bootstrap_token, str)
        or not hmac.compare_digest(configured, bootstrap_token)
    ):
        raise HumanMembershipRejected(403, "operator bootstrap credential is invalid")
    reason = _required_reason(reason)
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_required(db, tenant_id)
        principal = _principal(db, tenant_id, principal_id)
        existing_admin = db.scalar(select(HumanMembershipRole).where(
            HumanMembershipRole.tenant_id == tenant_id,
            HumanMembershipRole.role == "tenant_identity_admin",
            HumanMembershipRole.status == "ACTIVE",
        ))
        if existing_admin is not None:
            raise HumanMembershipRejected(409, "tenant identity admin is already bootstrapped")
        role = HumanMembershipRole(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            principal_id=principal_id,
            role="tenant_identity_admin",
            status="ACTIVE",
            created_by_ref="ola-platform-bootstrap",
        )
        db.add(role)
        evidence = _append_evidence_locked(db, tenant_id, "human.identity_admin_bootstrapped", {
            "tenant_id": tenant_id,
            "principal_id": principal_id,
            "person_ref": principal.person_ref,
            "source": principal.person_key_source,
            "reason": reason,
            "decision": "BOOTSTRAPPED",
            "bootstrap_at": int(time.time()),
        })
        db.commit()
    return {"status": "BOOTSTRAPPED", "principal_id": principal_id, "evidence_id": evidence["id"]}



def require_human_operator(request, *, required_role: str, max_auth_age_seconds: int = 300) -> HumanPrincipalContext:
    """Require an authenticated OIDC operator with recent MFA step-up and role."""
    from app.human_identity.sessions import HumanSessionRejected, require_human_session

    if required_role not in ALLOWED_ROLES:
        raise HumanMembershipRejected(400, "required Human Gate role is not recognized")
    try:
        session = require_human_session(request)
    except HumanSessionRejected as exc:
        raise HumanMembershipRejected(exc.code, str(exc)) from exc
    now = int(time.time())
    if (
        not session.mfa_verified
        or type(session.auth_time) is not int
        or type(max_auth_age_seconds) is not int
        or not 30 <= max_auth_age_seconds <= 3600
        or session.auth_time > now
        or now - session.auth_time > max_auth_age_seconds
    ):
        raise HumanMembershipRejected(
            403,
            "fresh MFA step-up required; authenticate at /human/oidc/{tenant_id}/login?step_up=true",
        )
    context = resolve_human_principal_context(
        tenant_id=session.tenant_id,
        principal_id=session.principal_ref,
        auth_time=session.auth_time,
        mfa_verified=session.mfa_verified,
    )
    if required_role not in context.roles:
        raise HumanMembershipRejected(403, f"active {required_role} membership is required")
    return context
