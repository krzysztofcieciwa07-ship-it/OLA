"""Order-scoped customer bundle grants and per-transfer attempt lifecycle."""
from __future__ import annotations

import time
import uuid

from sqlalchemy import func, select

from app.database import SessionLocal, begin_write_transaction
from app.hashchain import GENESIS_HASH, compute_record_hash_v2, sealed_payload_json
from app.models import (
    CheckoutOrder,
    CustomerBundleDeliveryAttempt,
    CustomerBundleRecipientGrant,
    CustomerEvidenceBundle,
    EvidenceRecord,
    HumanMembershipRole,
    HumanPrincipal,
    Tenant,
    TenantIdentityPolicy,
)
from app.human_identity.membership import HumanMembershipRejected, assert_distinct_humans


class CustomerBundleDeliveryRejected(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _assert_distinct_humans(*person_refs) -> None:
    try:
        assert_distinct_humans(*person_refs)
    except HumanMembershipRejected as exc:
        raise CustomerBundleDeliveryRejected(exc.code, str(exc)) from exc


def _reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CustomerBundleDeliveryRejected(400, "a nonempty reason is required")
    value = value.strip()
    if len(value) > 1000:
        raise CustomerBundleDeliveryRejected(400, "reason exceeds 1000 characters")
    return value


def _require_oidc_policy(db, tenant_id: str) -> None:
    tenant = db.get(Tenant, tenant_id)
    policy = db.get(TenantIdentityPolicy, tenant_id)
    if tenant is None:
        raise CustomerBundleDeliveryRejected(404, "tenant not found")
    if policy is None or policy.human_gate_mode != "OIDC_REQUIRED":
        raise CustomerBundleDeliveryRejected(
            403, "customer bundle delivery requires persistent OIDC_REQUIRED Human Identity policy"
        )


def _principal(db, tenant_id: str, principal_id: str, person_ref: str) -> HumanPrincipal:
    principal = db.scalar(select(HumanPrincipal).where(
        HumanPrincipal.id == principal_id,
        HumanPrincipal.tenant_id == tenant_id,
    ).with_for_update())
    if (
        principal is None
        or principal.status != "ACTIVE"
        or not principal.person_ref
        or principal.person_ref != person_ref
    ):
        raise CustomerBundleDeliveryRejected(
            403, "active HR-bound Human Identity principal is required"
        )
    return principal


def _require_role(db, tenant_id: str, principal_id: str, role: str) -> None:
    membership = db.scalar(select(HumanMembershipRole).where(
        HumanMembershipRole.tenant_id == tenant_id,
        HumanMembershipRole.principal_id == principal_id,
        HumanMembershipRole.role == role,
        HumanMembershipRole.status == "ACTIVE",
    ))
    if membership is None:
        raise CustomerBundleDeliveryRejected(403, f"active {role} membership is required")


def _require_order(db, tenant_id: str, order_id: str) -> CheckoutOrder:
    order = db.scalar(select(CheckoutOrder).where(
        CheckoutOrder.id == order_id,
        CheckoutOrder.tenant_id == tenant_id,
    ).with_for_update())
    if order is None:
        raise CustomerBundleDeliveryRejected(404, "paid order not found")
    if order.status not in {"REPORT_APPROVED", "REPORT_DELIVERED"}:
        raise CustomerBundleDeliveryRejected(
            409, "customer bundle grant requires an independently approved report"
        )
    return order


def _append_locked(db, tenant_id: str, record_type: str, payload: dict) -> dict:
    latest = db.scalar(select(EvidenceRecord).where(
        EvidenceRecord.tenant_id == tenant_id,
    ).order_by(EvidenceRecord.seq.desc()).limit(1))
    seq = latest.seq + 1 if latest is not None else 0
    prev_hash = latest.record_hash if latest is not None else GENESIS_HASH
    payload_json = sealed_payload_json(record_type, payload, producer="ola_runtime")
    record_hash = compute_record_hash_v2(
        tenant_id, seq, prev_hash, record_type, "ola_runtime", payload_json,
    )
    record_id = str(uuid.uuid4())
    db.add(EvidenceRecord(
        id=record_id,
        tenant_id=tenant_id,
        seq=seq,
        record_type=record_type,
        payload_json=payload_json,
        prev_hash=prev_hash,
        record_hash=record_hash,
    ))
    db.flush()
    return {"id": record_id, "seq": seq, "record_hash": record_hash}


def request_recipient_grant(
    *,
    tenant_id: str,
    order_id: str,
    requester_principal_id: str,
    requester_person_ref: str,
    recipient_principal_id: str,
    recipient_person_ref: str,
    reason: str,
    expires_at: int,
) -> dict:
    """Create a pending order-only grant request; a second human must approve it."""
    reason = _reason(reason)
    if not all(isinstance(value, str) and value for value in (
        tenant_id, order_id, requester_principal_id, requester_person_ref,
        recipient_principal_id, recipient_person_ref,
    )):
        raise CustomerBundleDeliveryRejected(400, "tenant, order, requester and recipient identities are required")
    now = int(time.time())
    if type(expires_at) is not int or expires_at <= now:
        raise CustomerBundleDeliveryRejected(400, "grant expiry must be a future Unix timestamp")

    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        _require_order(db, tenant_id, order_id)
        requester = _principal(db, tenant_id, requester_principal_id, requester_person_ref)
        recipient = _principal(db, tenant_id, recipient_principal_id, recipient_person_ref)
        _require_role(db, tenant_id, requester_principal_id, "tenant_identity_admin")
        _require_role(db, tenant_id, recipient_principal_id, "recipient")
        _assert_distinct_humans(requester.person_ref, recipient.person_ref)

        existing = db.scalar(select(CustomerBundleRecipientGrant).where(
            CustomerBundleRecipientGrant.tenant_id == tenant_id,
            CustomerBundleRecipientGrant.order_id == order_id,
            CustomerBundleRecipientGrant.recipient_person_ref == recipient.person_ref,
            CustomerBundleRecipientGrant.status.in_({"PENDING", "ACTIVE"}),
        ).with_for_update())
        if existing is not None:
            raise CustomerBundleDeliveryRejected(409, "recipient already has a pending or active grant for this order")

        grant_id = str(uuid.uuid4())
        grant = CustomerBundleRecipientGrant(
            id=grant_id,
            tenant_id=tenant_id,
            order_id=order_id,
            recipient_principal_id=recipient_principal_id,
            recipient_person_ref=recipient.person_ref,
            requester_principal_id=requester_principal_id,
            requester_person_ref=requester.person_ref,
            status="PENDING",
            reason=reason,
            requested_at=now,
            expires_at=expires_at,
        )
        db.add(grant)
        evidence = _append_locked(db, tenant_id, "revenue.customer_bundle_recipient_grant_requested", {
            "order_id": order_id,
            "grant_id": grant_id,
            "requester_person_ref": requester.person_ref,
            "recipient_person_ref": recipient.person_ref,
            "reason": reason,
            "expires_at": expires_at,
            "decision": "PENDING",
            "requested_at": now,
        })
        grant.request_evidence_id = evidence["id"]
        db.commit()

    return {"status": "PENDING", "grant_id": grant_id, "order_id": order_id}


def approve_recipient_grant(
    *,
    tenant_id: str,
    order_id: str,
    grant_id: str,
    approver_principal_id: str,
    approver_person_ref: str,
    reason: str,
    now: int | None = None,
) -> dict:
    """Activate the grant only after a different HR-backed tenant administrator approves."""
    reason = _reason(reason)
    approved_at = int(time.time()) if now is None else now
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        approver = _principal(db, tenant_id, approver_principal_id, approver_person_ref)
        _require_role(db, tenant_id, approver_principal_id, "tenant_identity_admin")
        grant = db.scalar(select(CustomerBundleRecipientGrant).where(
            CustomerBundleRecipientGrant.id == grant_id,
            CustomerBundleRecipientGrant.tenant_id == tenant_id,
            CustomerBundleRecipientGrant.order_id == order_id,
        ).with_for_update())
        if grant is None:
            raise CustomerBundleDeliveryRejected(404, "recipient grant request not found")
        if grant.status != "PENDING":
            raise CustomerBundleDeliveryRejected(409, "recipient grant request is not pending")
        if grant.expires_at <= approved_at:
            grant.status = "EXPIRED"
            db.commit()
            raise CustomerBundleDeliveryRejected(409, "recipient grant request has expired")
        recipient = _principal(
            db, tenant_id, grant.recipient_principal_id, grant.recipient_person_ref,
        )
        _assert_distinct_humans(
            grant.requester_person_ref, approver.person_ref, recipient.person_ref,
        )
        grant.status = "ACTIVE"
        grant.approver_principal_id = approver_principal_id
        grant.approver_person_ref = approver.person_ref
        grant.approved_at = approved_at
        evidence = _append_locked(db, tenant_id, "revenue.customer_bundle_recipient_grant_approved", {
            "order_id": grant.order_id,
            "grant_id": grant_id,
            "requester_person_ref": grant.requester_person_ref,
            "approver_person_ref": approver.person_ref,
            "recipient_person_ref": recipient.person_ref,
            "reason": reason,
            "decision": "ACTIVE",
            "approved_at": approved_at,
            "expires_at": grant.expires_at,
        })
        grant.approval_evidence_id = evidence["id"]
        order_id = grant.order_id
        db.commit()

    return {"status": "ACTIVE", "grant_id": grant_id, "order_id": order_id}


def revoke_recipient_grant(
    *,
    tenant_id: str,
    order_id: str,
    grant_id: str,
    actor_principal_id: str,
    actor_person_ref: str,
    reason: str,
    now: int | None = None,
) -> dict:
    """Immediately revoke one order-scoped grant; revocation is separately evidenced."""
    reason = _reason(reason)
    revoked_at = int(time.time()) if now is None else now
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        actor = _principal(db, tenant_id, actor_principal_id, actor_person_ref)
        _require_role(db, tenant_id, actor_principal_id, "tenant_identity_admin")
        grant = db.scalar(select(CustomerBundleRecipientGrant).where(
            CustomerBundleRecipientGrant.id == grant_id,
            CustomerBundleRecipientGrant.tenant_id == tenant_id,
            CustomerBundleRecipientGrant.order_id == order_id,
        ).with_for_update())
        if grant is None:
            raise CustomerBundleDeliveryRejected(404, "recipient grant not found")
        if grant.status not in {"PENDING", "ACTIVE"}:
            raise CustomerBundleDeliveryRejected(409, "recipient grant is not revocable")
        grant.status = "REVOKED"
        grant.revoked_at = revoked_at
        evidence = _append_locked(db, tenant_id, "revenue.customer_bundle_recipient_grant_revoked", {
            "order_id": grant.order_id,
            "grant_id": grant_id,
            "actor_person_ref": actor.person_ref,
            "recipient_person_ref": grant.recipient_person_ref,
            "reason": reason,
            "decision": "REVOKED",
            "revoked_at": revoked_at,
        })
        grant.revocation_evidence_id = evidence["id"]
        order_id = grant.order_id
        db.commit()
    return {"status": "REVOKED", "grant_id": grant_id, "order_id": order_id}


def begin_delivery_attempt(
    *,
    tenant_id: str,
    order_id: str,
    bundle_id: str,
    recipient_principal_id: str,
    recipient_person_ref: str,
    now: int | None = None,
) -> dict:
    """Authorize and record a single transfer attempt without mutating bundle/grant state."""
    attempted_at = int(time.time()) if now is None else now
    if type(attempted_at) is not int:
        raise CustomerBundleDeliveryRejected(400, "attempt time must be an integer Unix timestamp")
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        recipient = _principal(
            db, tenant_id, recipient_principal_id, recipient_person_ref,
        )
        _require_role(db, tenant_id, recipient_principal_id, "recipient")
        bundle = db.scalar(select(CustomerEvidenceBundle).where(
            CustomerEvidenceBundle.id == bundle_id,
            CustomerEvidenceBundle.tenant_id == tenant_id,
            CustomerEvidenceBundle.order_id == order_id,
        ).with_for_update())
        if bundle is None:
            raise CustomerBundleDeliveryRejected(404, "customer evidence bundle not found")

        grants = db.scalars(select(CustomerBundleRecipientGrant).where(
            CustomerBundleRecipientGrant.tenant_id == tenant_id,
            CustomerBundleRecipientGrant.order_id == order_id,
            CustomerBundleRecipientGrant.recipient_principal_id == recipient_principal_id,
            CustomerBundleRecipientGrant.recipient_person_ref == recipient.person_ref,
        ).order_by(CustomerBundleRecipientGrant.requested_at.desc()).with_for_update()).all()
        grant = grants[0] if grants else None
        reason = None
        status = "STARTED"
        if bundle.status != "SIGNED":
            status = "BLOCKED"
            reason = {
                "EXPIRED": "BUNDLE_EXPIRED",
                "REVOKED": "BUNDLE_REVOKED",
                "INVALID": "BUNDLE_INVALID",
            }.get(bundle.status, "BUNDLE_NOT_SIGNED")
        elif bundle.expires_at is not None and bundle.expires_at <= attempted_at:
            bundle.status = "EXPIRED"
            bundle.status_reason = "bundle expiry reached"
            status = "BLOCKED"
            reason = "BUNDLE_EXPIRED"
        elif grant is None or grant.status != "ACTIVE":
            status = "BLOCKED"
            reason = "RECIPIENT_GRANT_INACTIVE"
        elif grant.expires_at <= attempted_at:
            grant.status = "EXPIRED"
            status = "BLOCKED"
            reason = "RECIPIENT_GRANT_EXPIRED"

        attempt_no = (db.scalar(select(func.max(
            CustomerBundleDeliveryAttempt.attempt_no,
        )).where(
            CustomerBundleDeliveryAttempt.bundle_id == bundle_id,
            CustomerBundleDeliveryAttempt.recipient_person_ref == recipient.person_ref,
        )) or 0) + 1
        attempt_id = str(uuid.uuid4())
        grant_id_value = grant.id if grant is not None else None
        attempt = CustomerBundleDeliveryAttempt(
            id=attempt_id,
            tenant_id=tenant_id,
            order_id=order_id,
            bundle_id=bundle_id,
            grant_id=grant_id_value,
            recipient_principal_id=recipient_principal_id,
            recipient_person_ref=recipient.person_ref,
            attempt_no=attempt_no,
            status=status,
            reason=reason,
            created_at=attempted_at,
            started_at=attempted_at if status == "STARTED" else None,
        )
        db.add(attempt)
        evidence = _append_locked(db, tenant_id,
            "revenue.customer_bundle_delivery_attempt_started" if status == "STARTED"
            else "revenue.customer_bundle_delivery_attempt_blocked",
            {
                "order_id": order_id,
                "bundle_id": bundle_id,
                "grant_id": grant_id_value,
                "attempt_id": attempt_id,
                "attempt_no": attempt_no,
                "recipient_person_ref": recipient.person_ref,
                "status": status,
                "reason": reason,
                "attempted_at": attempted_at,
            },
        )
        db.commit()

    return {
        "status": status,
        "attempt_id": attempt_id,
        "attempt_no": attempt_no,
        "grant_id": grant_id_value,
        "reason": reason,
        "evidence_id": evidence["id"],
    }


def complete_delivery_attempt(
    *,
    tenant_id: str,
    attempt_id: str,
    recipient_principal_id: str,
    recipient_person_ref: str,
    now: int | None = None,
) -> dict:
    """Mark a transfer complete only after the storage/stream adapter confirms completion."""
    completed_at = int(time.time()) if now is None else now
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        recipient = _principal(
            db, tenant_id, recipient_principal_id, recipient_person_ref,
        )
        attempt = db.scalar(select(CustomerBundleDeliveryAttempt).where(
            CustomerBundleDeliveryAttempt.id == attempt_id,
            CustomerBundleDeliveryAttempt.tenant_id == tenant_id,
        ).with_for_update())
        if attempt is None:
            raise CustomerBundleDeliveryRejected(404, "delivery attempt not found")
        if (
            attempt.recipient_principal_id != recipient_principal_id
            or attempt.recipient_person_ref != recipient.person_ref
        ):
            raise CustomerBundleDeliveryRejected(403, "delivery attempt belongs to another recipient")
        if attempt.status != "STARTED":
            raise CustomerBundleDeliveryRejected(409, "only a started delivery attempt can complete")
        if type(completed_at) is not int or completed_at < attempt.started_at:
            raise CustomerBundleDeliveryRejected(400, "completion time precedes transfer start")
        attempt.status = "COMPLETED"
        attempt.completed_at = completed_at
        evidence = _append_locked(db, tenant_id, "revenue.customer_bundle_delivery_attempt_completed", {
            "order_id": attempt.order_id,
            "bundle_id": attempt.bundle_id,
            "grant_id": attempt.grant_id,
            "attempt_id": attempt_id,
            "attempt_no": attempt.attempt_no,
            "recipient_person_ref": recipient.person_ref,
            "status": "COMPLETED",
            "completed_at": completed_at,
        })
        db.commit()
    return {"status": "COMPLETED", "attempt_id": attempt_id, "evidence_id": evidence["id"]}



def acknowledge_delivery_attempt(
    *,
    tenant_id: str,
    order_id: str,
    bundle_id: str,
    attempt_id: str,
    recipient_principal_id: str,
    recipient_person_ref: str,
    now: int | None = None,
) -> dict:
    """Record an explicit recipient acknowledgement after a completed transfer.

    This proves that the authenticated recipient account submitted an
    acknowledgement. It does not prove that a human read or accepted the report.
    """
    acknowledged_at = int(time.time()) if now is None else now
    if type(acknowledged_at) is not int:
        raise CustomerBundleDeliveryRejected(400, "acknowledgement time must be an integer Unix timestamp")
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        recipient = _principal(
            db, tenant_id, recipient_principal_id, recipient_person_ref,
        )
        _require_role(db, tenant_id, recipient_principal_id, "recipient")
        attempt = db.scalar(select(CustomerBundleDeliveryAttempt).where(
            CustomerBundleDeliveryAttempt.id == attempt_id,
            CustomerBundleDeliveryAttempt.tenant_id == tenant_id,
            CustomerBundleDeliveryAttempt.order_id == order_id,
            CustomerBundleDeliveryAttempt.bundle_id == bundle_id,
        ).with_for_update())
        if attempt is None:
            raise CustomerBundleDeliveryRejected(404, "delivery attempt not found")
        if (
            attempt.recipient_principal_id != recipient_principal_id
            or attempt.recipient_person_ref != recipient.person_ref
        ):
            raise CustomerBundleDeliveryRejected(403, "delivery attempt belongs to another recipient")
        if attempt.status != "COMPLETED" or attempt.completed_at is None:
            raise CustomerBundleDeliveryRejected(409, "only a completed transfer can be acknowledged")
        if attempt.acknowledged_at is not None or attempt.acknowledgement_evidence_id:
            raise CustomerBundleDeliveryRejected(409, "delivery attempt has already been acknowledged")
        if acknowledged_at < attempt.completed_at:
            raise CustomerBundleDeliveryRejected(400, "acknowledgement time precedes transfer completion")

        evidence = _append_locked(
            db, tenant_id,
            "revenue.customer_bundle_delivery_attempt_acknowledged",
            {
                "order_id": attempt.order_id,
                "bundle_id": attempt.bundle_id,
                "grant_id": attempt.grant_id,
                "attempt_id": attempt_id,
                "attempt_no": attempt.attempt_no,
                "recipient_person_ref": recipient.person_ref,
                "status": "ACKNOWLEDGED",
                "transfer_completed_at": attempt.completed_at,
                "acknowledged_at": acknowledged_at,
                "meaning": "authenticated_recipient_acknowledged_transfer_not_report_comprehension",
            },
        )
        attempt.acknowledged_at = acknowledged_at
        attempt.acknowledgement_evidence_id = evidence["id"]
        db.commit()

    return {
        "status": "ACKNOWLEDGED",
        "attempt_id": attempt_id,
        "acknowledgement_evidence_id": evidence["id"],
        "acknowledged_at": acknowledged_at,
    }


def fail_delivery_attempt(
    *,
    tenant_id: str,
    attempt_id: str,
    recipient_principal_id: str,
    recipient_person_ref: str,
    reason: str,
    now: int | None = None,
) -> dict:
    """Record a failed stream attempt separately; it never changes bundle or grant state."""
    failure_reason = _reason(reason)
    failed_at = int(time.time()) if now is None else now
    with SessionLocal() as db:
        begin_write_transaction(db, tenant_id=tenant_id)
        _require_oidc_policy(db, tenant_id)
        recipient = _principal(
            db, tenant_id, recipient_principal_id, recipient_person_ref,
        )
        attempt = db.scalar(select(CustomerBundleDeliveryAttempt).where(
            CustomerBundleDeliveryAttempt.id == attempt_id,
            CustomerBundleDeliveryAttempt.tenant_id == tenant_id,
        ).with_for_update())
        if attempt is None:
            raise CustomerBundleDeliveryRejected(404, "delivery attempt not found")
        if (
            attempt.recipient_principal_id != recipient_principal_id
            or attempt.recipient_person_ref != recipient.person_ref
        ):
            raise CustomerBundleDeliveryRejected(403, "delivery attempt belongs to another recipient")
        if attempt.status != "STARTED":
            raise CustomerBundleDeliveryRejected(409, "only a started delivery attempt can fail")
        attempt.status = "FAILED"
        attempt.reason = "TRANSFER_FAILED"
        attempt.failed_at = failed_at
        evidence = _append_locked(db, tenant_id, "revenue.customer_bundle_delivery_attempt_failed", {
            "order_id": attempt.order_id,
            "bundle_id": attempt.bundle_id,
            "grant_id": attempt.grant_id,
            "attempt_id": attempt_id,
            "attempt_no": attempt.attempt_no,
            "recipient_person_ref": recipient.person_ref,
            "reason": failure_reason,
            "status": "FAILED",
            "failed_at": failed_at,
        })
        db.commit()
    return {"status": "FAILED", "attempt_id": attempt_id, "evidence_id": evidence["id"]}
