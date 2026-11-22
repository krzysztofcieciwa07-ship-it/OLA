"""External Signed Approval v1 intake for tenant-scoped paid orders.

The caller must authenticate the OIDC bearer token before calling this
service. The private Ed25519 signing key stays outside OLA; this service only
verifies an externally signed envelope and atomically records the approval and
single execution outbox job. It does not execute the job or consume its nonce.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .approval_contract_v1 import (
    ApprovalContractError,
    approval_is_current,
    oidc_session_fingerprint,
    signing_input,
    validate_approval_semantics,
    verify_signed_approval_envelope,
)
from .approval_identity import VerifiedSubject
from .approval_membership import (
    HumanGateMembershipError,
    resolve_human_gate_membership,
)
from .database import begin_write_transaction
from .evidence_writer import append_evidence_v4_locked
from .models import (
    ApiKey,
    CheckoutExecutionJob,
    CheckoutOrderControl,
    EvidenceRecord,
    HumanGateMembership,
)
from .order_approval import _validate_paid_order
from .runtime_provenance import runtime_source_commit
from .signed_approval_runtime import (
    SignedApprovalRuntimeRejected,
    _trusted_public_keys,
    signed_envelope_sha256,
    verify_paid_order_signed_approval,
)


class SignedApprovalSubmissionRejected(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


_PAYLOAD_KEYS = {
    "schema", "approval_id", "tenant_id", "operation_id", "request", "effect",
    "decision", "effect_authorized", "execution_observed", "author", "reviewer",
    "prior_approvers", "reviewer_authentication", "policy", "evidence", "runtime",
    "reason", "nonce", "issued_at", "expires_at", "closure",
}
_ACTOR_KEYS = {
    "principal_id", "tenant_id", "issuer", "subject_fingerprint",
    "fingerprint_key_id", "role", "membership_version",
}
_MAX_ENVELOPE_BYTES = 66_000
_MAX_REASON_CHARS = 1000
_MAX_STEP_UP_AGE_SECONDS = 300


def _strict_object(value, expected: set[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise SignedApprovalSubmissionRejected(400, f"signed approval {name} shape is invalid")
    return value


def _identity_fingerprint_config() -> tuple[bytes, str]:
    encoded = os.getenv("OLA_APPROVAL_IDENTITY_FINGERPRINT_KEY_B64", "")
    key_id = os.getenv("OLA_APPROVAL_IDENTITY_FINGERPRINT_KEY_ID", "")
    if (
        not isinstance(encoded, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{43,}", encoded) is None
        or not isinstance(key_id, str)
        or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key_id) is None
    ):
        raise SignedApprovalSubmissionRejected(
            503, "Human Gate identity fingerprint key is not configured"
        )
    try:
        key = base64.urlsafe_b64decode(encoded + "=" * ((4 - len(encoded) % 4) % 4))
    except (ValueError, base64.binascii.Error):
        raise SignedApprovalSubmissionRejected(
            503, "Human Gate identity fingerprint key is invalid"
        ) from None
    if len(key) < 32 or base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii") != encoded:
        raise SignedApprovalSubmissionRejected(
            503, "Human Gate identity fingerprint key must be canonical base64url and at least 32 bytes"
        )
    return key, key_id


def _required_step_up_policy() -> tuple[str, frozenset[str]]:
    acr = os.getenv("OLA_APPROVAL_REQUIRED_ACR", "")
    amr = frozenset(
        item.strip()
        for item in os.getenv("OLA_APPROVAL_REQUIRED_AMR", "").split(",")
        if item.strip()
    )
    if (
        not isinstance(acr, str)
        or not acr
        or len(acr) > 256
        or not amr
        or any(len(item) > 64 for item in amr)
    ):
        raise SignedApprovalSubmissionRejected(
            503, "Human Gate step-up authentication policy is not configured"
        )
    return acr, amr


def _actor_matches_membership(actor: dict, membership: HumanGateMembership | None, *, tenant_id: str, role: str):
    if (
        membership is None
        or membership.id != actor["principal_id"]
        or membership.tenant_id != tenant_id
        or actor["tenant_id"] != tenant_id
        or membership.issuer != actor["issuer"]
        or membership.subject_fingerprint != actor["subject_fingerprint"]
        or membership.fingerprint_key_id != actor["fingerprint_key_id"]
        or membership.role != role
        or actor["role"] != role
        or membership.membership_version != actor["membership_version"]
        or membership.active is not True
        or membership.revoked_at is not None
    ):
        raise SignedApprovalSubmissionRejected(
            403, f"current {role} membership does not match the signed approval"
        )


def _validate_live_reviewer_session(
    payload: dict,
    verified_subject: VerifiedSubject,
    *,
    fingerprint_key: bytes,
    fingerprint_key_id: str,
    now: datetime,
):
    reviewer = payload["reviewer"]
    authentication = payload["reviewer_authentication"]
    required_acr, required_amr = _required_step_up_policy()
    if (
        verified_subject.auth_time is None
        or verified_subject.acr is None
        or not verified_subject.amr
        or verified_subject.session_id is None
    ):
        raise SignedApprovalSubmissionRejected(
            401, "OIDC bearer token lacks required step-up or session claims"
        )
    if (
        verified_subject.acr != required_acr
        or not required_amr.issubset(set(verified_subject.amr))
        or authentication.get("acr") != verified_subject.acr
        or tuple(authentication.get("amr", ())) != tuple(verified_subject.amr)
    ):
        raise SignedApprovalSubmissionRejected(
            403, "live OIDC reviewer step-up claims do not match the signed approval"
        )
    now_seconds = int(now.timestamp())
    if (
        verified_subject.auth_time > now_seconds
        or now_seconds - verified_subject.auth_time > _MAX_STEP_UP_AGE_SECONDS
    ):
        raise SignedApprovalSubmissionRejected(
            401, "OIDC reviewer step-up authentication is too old or in the future"
        )
    live_auth_time = datetime.fromtimestamp(
        verified_subject.auth_time, tz=timezone.utc,
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    if authentication.get("auth_time") != live_auth_time:
        raise SignedApprovalSubmissionRejected(
            403, "signed approval auth_time does not match the live OIDC session"
        )
    session = oidc_session_fingerprint(
        fingerprint_key,
        fingerprint_key_id,
        verified_subject.tenant_id,
        verified_subject.issuer,
        verified_subject.subject,
        verified_subject.session_id,
    )
    if (
        authentication.get("session_fingerprint") != session["value"]
        or reviewer.get("issuer") != verified_subject.issuer
        or reviewer.get("tenant_id") != verified_subject.tenant_id
    ):
        raise SignedApprovalSubmissionRejected(
            403, "signed approval reviewer is not bound to the live OIDC session"
        )




def prepare_signed_paid_order_approval_challenge(
    db,
    *,
    order_id: str,
    reason: str,
    verified_subject: VerifiedSubject,
    now: datetime | None = None,
) -> dict:
    """Prepare read-only Signed Approval v1 bytes for an external KMS/HSM signer.

    This function never persists an approval, creates an execution job, consumes
    a nonce, or signs bytes. The caller receives the exact domain-separated
    canonical input to pass to an independently authorized signing service.
    """
    if db.get_bind().dialect.name != "postgresql":
        raise SignedApprovalSubmissionRejected(
            503, "signed Human Gate approval challenges require PostgreSQL"
        )
    if not isinstance(order_id, str):
        raise SignedApprovalSubmissionRejected(400, "order_id is invalid")
    try:
        normalized_order_id = str(uuid.UUID(order_id))
    except (ValueError, TypeError, AttributeError):
        raise SignedApprovalSubmissionRejected(400, "order_id must be a UUID") from None
    if normalized_order_id != order_id:
        raise SignedApprovalSubmissionRejected(400, "order_id must be a canonical lowercase UUID")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > _MAX_REASON_CHARS:
        raise SignedApprovalSubmissionRejected(400, "approval reason must contain 1 to 1000 characters")
    if not isinstance(verified_subject, VerifiedSubject):
        raise SignedApprovalSubmissionRejected(401, "verified OIDC reviewer identity is required")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current):
        raise SignedApprovalSubmissionRejected(500, "approval validation clock must be timezone-aware UTC")

    fingerprint_key, fingerprint_key_id = _identity_fingerprint_config()
    source_commit = runtime_source_commit()
    policy_version = os.getenv("OLA_APPROVAL_POLICY_VERSION", "")
    policy_sha256 = os.getenv("OLA_APPROVAL_POLICY_SHA256", "")
    required_acr, required_amr = _required_step_up_policy()
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or not policy_version
        or re.fullmatch(r"[0-9a-f]{64}", policy_sha256) is None
    ):
        raise SignedApprovalSubmissionRejected(
            503, "current runtime source or approval policy is not configured"
        )
    if (
        verified_subject.tenant_id is None
        or verified_subject.issuer is None
        or verified_subject.subject is None
        or verified_subject.auth_time is None
        or verified_subject.acr != required_acr
        or not required_amr.issubset(set(verified_subject.amr))
        or not verified_subject.session_id
    ):
        raise SignedApprovalSubmissionRejected(
            401, "OIDC bearer token lacks the required reviewer step-up session"
        )
    now_seconds = int(current.timestamp())
    if (
        verified_subject.auth_time > now_seconds
        or now_seconds - verified_subject.auth_time > _MAX_STEP_UP_AGE_SECONDS
    ):
        raise SignedApprovalSubmissionRejected(
            401, "OIDC reviewer step-up authentication is too old or in the future"
        )

    try:
        resolved_reviewer = resolve_human_gate_membership(
            db,
            verified_subject,
            resource_tenant_id=verified_subject.tenant_id,
            fingerprint_key=fingerprint_key,
            fingerprint_key_id=fingerprint_key_id,
            required_role="execution_approver",
        )
    except HumanGateMembershipError as exc:
        raise SignedApprovalSubmissionRejected(403, str(exc)) from None

    requester_id = None
    with db.no_autoflush:
        control_hint = db.scalar(
            select(CheckoutOrderControl).where(
                CheckoutOrderControl.order_id == order_id,
                CheckoutOrderControl.tenant_id == verified_subject.tenant_id,
            )
        )
    if control_hint is None:
        raise SignedApprovalSubmissionRejected(404, "paid order not found")

    author_membership = db.get(HumanGateMembership, control_hint.requester_id)
    if (
        author_membership is None
        or author_membership.id != control_hint.requester_id
        or author_membership.tenant_id != verified_subject.tenant_id
        or author_membership.role != "requester"
        or author_membership.active is not True
        or author_membership.revoked_at is not None
        or not isinstance(author_membership.membership_version, int)
        or isinstance(author_membership.membership_version, bool)
        or author_membership.membership_version < 1
    ):
        raise SignedApprovalSubmissionRejected(
            403, "original requester does not have a current requester membership"
        )
    if author_membership.id == resolved_reviewer.principal_id:
        raise SignedApprovalSubmissionRejected(403, "request author cannot approve their own order")
    requester_id = author_membership.id
    requester_key = db.get(ApiKey, requester_id)
    if requester_key is None or requester_key.tenant_id != verified_subject.tenant_id:
        raise SignedApprovalSubmissionRejected(
            403, "original requester is not linked to the paid-order technical identity"
        )

    tip_hash = db.scalar(
        select(EvidenceRecord.record_hash)
        .where(EvidenceRecord.tenant_id == verified_subject.tenant_id)
        .order_by(EvidenceRecord.seq.desc())
        .limit(1)
    )
    if not isinstance(tip_hash, str) or re.fullmatch(r"[0-9a-f]{64}", tip_hash) is None:
        raise SignedApprovalSubmissionRejected(409, "tenant evidence chain has no valid current tip")

    try:
        order, control, _payment, checkout_proof, payment_proof, private_task, _rows, records = _validate_paid_order(
            db,
            tenant_id=verified_subject.tenant_id,
            order_id=order_id,
            approver_id=resolved_reviewer.principal_id,
            tip_hash=tip_hash,
        )
    except ValueError as exc:
        raise SignedApprovalSubmissionRejected(getattr(exc, "code", 409), str(exc)) from None

    if (
        control.signed_approval_envelope_json
        or control.approval_record_hash
        or db.scalar(select(CheckoutExecutionJob).where(
            CheckoutExecutionJob.order_id == order_id
        )) is not None
    ):
        raise SignedApprovalSubmissionRejected(409, "order already has an approval or execution job")

    def actor(membership):
        return {
            "principal_id": membership.id,
            "tenant_id": membership.tenant_id,
            "issuer": membership.issuer,
            "subject_fingerprint": membership.subject_fingerprint,
            "fingerprint_key_id": membership.fingerprint_key_id,
            "role": membership.role,
            "membership_version": membership.membership_version,
        }

    auth_time_text = datetime.fromtimestamp(
        verified_subject.auth_time, tz=timezone.utc,
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    session_fingerprint = oidc_session_fingerprint(
        fingerprint_key,
        fingerprint_key_id,
        verified_subject.tenant_id,
        verified_subject.issuer,
        verified_subject.subject,
        verified_subject.session_id,
    )["value"]
    checkout_record = {
        "id": checkout_proof["id"],
        "sequence": checkout_proof["seq"],
        "record_type": checkout_proof["record_type"],
        "record_hash": checkout_proof["record_hash"],
    }
    payment_record = {
        "id": payment_proof["id"],
        "sequence": payment_proof["seq"],
        "record_type": payment_proof["record_type"],
        "record_hash": payment_proof["record_hash"],
    }
    evidence_references = [checkout_record, payment_record]
    tip_record = next(
        (record for record in records if record["record_hash"] == tip_hash),
        None,
    )
    if tip_record is None:
        raise SignedApprovalSubmissionRejected(409, "current evidence tip is missing from the verified chain")
    if tip_record["id"] not in {checkout_record["id"], payment_record["id"]}:
        if tip_record["seq"] <= payment_proof["seq"]:
            raise SignedApprovalSubmissionRejected(409, "current evidence tip does not follow payment confirmation")
        evidence_references.append({
            "id": tip_record["id"],
            "sequence": tip_record["seq"],
            "record_type": tip_record["record_type"],
            "record_hash": tip_record["record_hash"],
        })
    reviewer_actor = {
        "principal_id": resolved_reviewer.principal_id,
        "tenant_id": resolved_reviewer.tenant_id,
        "issuer": resolved_reviewer.issuer,
        "subject_fingerprint": resolved_reviewer.subject_fingerprint,
        "fingerprint_key_id": resolved_reviewer.fingerprint_key_id,
        "role": resolved_reviewer.role,
        "membership_version": resolved_reviewer.membership_version,
    }
    payload = {
        "schema": "ola.signed-approval/v1",
        "approval_id": str(uuid.uuid4()),
        "tenant_id": order.tenant_id,
        "operation_id": str(uuid.uuid4()),
        "request": {
            "action": "EXECUTE_PAID_ORDER",
            "resource_type": "checkout_order",
            "resource_id": order.id,
            "sha256": order.request_hash,
        },
        "effect": {
            "action": "QUEUE_SINGLE_EXECUTION",
            "target_id": order.id,
            "target_sha256": order.request_hash,
        },
        "decision": "ALLOW",
        "effect_authorized": True,
        "execution_observed": "NOT_STARTED",
        "author": actor(author_membership),
        "reviewer": reviewer_actor,
        "prior_approvers": [],
        "reviewer_authentication": {
            "auth_time": auth_time_text,
            "acr": verified_subject.acr,
            "amr": list(verified_subject.amr),
            "session_fingerprint": session_fingerprint,
        },
        "policy": {"version": policy_version, "sha256": policy_sha256},
        "evidence": {
            "tip_hash": tip_hash,
            "records": evidence_references,
        },
        "runtime": {"source_commit": source_commit},
        "reason": reason.strip(),
        "nonce": str(uuid.uuid4()),
        "issued_at": current.astimezone(timezone.utc).isoformat(
            timespec="seconds",
        ).replace("+00:00", "Z"),
        "expires_at": (current + timedelta(seconds=300)).astimezone(
            timezone.utc,
        ).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "closure": {"operational": "OPEN", "epistemic": "OPEN", "remedial": "OPEN"},
    }
    try:
        validate_approval_semantics(payload, now=current)
        if not approval_is_current(payload, now=current):
            raise ApprovalContractError("newly prepared approval is outside its validity window")
        _validate_live_reviewer_session(
            payload,
            verified_subject,
            fingerprint_key=fingerprint_key,
            fingerprint_key_id=fingerprint_key_id,
            now=current,
        )
        key_ids = sorted(_trusted_public_keys())
    except ApprovalContractError as exc:
        raise SignedApprovalSubmissionRejected(409, f"approval challenge contract is invalid: {exc}") from None
    except SignedApprovalRuntimeRejected as exc:
        raise SignedApprovalSubmissionRejected(503, f"approval signing trust configuration is unavailable: {exc}") from None

    signing_bytes = signing_input(payload)
    if len(signing_bytes) > 65_600:
        raise SignedApprovalSubmissionRejected(413, "canonical signing input exceeds size limit")
    return {
        "status": "CHALLENGE_READY",
        "order_id": order.id,
        "payload": payload,
        "signing": {
            "algorithm": "Ed25519",
            "domain": "OLA-SIGNED-APPROVAL/v1",
            "key_ids": key_ids,
            "input_encoding": "base64url",
            "input": base64.urlsafe_b64encode(signing_bytes).rstrip(b"=").decode("ascii"),
            "input_sha256": hashlib.sha256(signing_bytes).hexdigest(),
        },
        "expires_at": payload["expires_at"],
        "requires_external_signature": True,
        "private_key_available_in_ola": False,
    }


def accept_signed_paid_order_approval(
    db,
    *,
    order_id: str,
    envelope: object,
    verified_subject: VerifiedSubject,
    now: datetime | None = None,
) -> dict:
    """Verify a live OIDC reviewer and atomically queue one signed paid-order job."""
    if db.get_bind().dialect.name != "postgresql":
        raise SignedApprovalSubmissionRejected(
            503, "signed Human Gate approval intake requires PostgreSQL"
        )
    if not isinstance(order_id, str):
        raise SignedApprovalSubmissionRejected(400, "order_id is invalid")
    try:
        order_id = str(uuid.UUID(order_id))
    except (ValueError, TypeError, AttributeError):
        raise SignedApprovalSubmissionRejected(400, "order_id must be a UUID") from None
    if order_id != order_id.lower():
        raise SignedApprovalSubmissionRejected(400, "order_id must be a canonical lowercase UUID")
    if not isinstance(verified_subject, VerifiedSubject):
        raise SignedApprovalSubmissionRejected(401, "verified OIDC reviewer identity is required")

    try:
        encoded = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise SignedApprovalSubmissionRejected(400, "signed approval envelope is invalid JSON data") from None
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise SignedApprovalSubmissionRejected(413, "signed approval envelope exceeds size limit")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current):
        raise SignedApprovalSubmissionRejected(500, "approval validation clock must be timezone-aware UTC")

    fingerprint_key, fingerprint_key_id = _identity_fingerprint_config()

    try:
        verify_signed_approval_envelope(envelope, _trusted_public_keys())
    except (ApprovalContractError, SignedApprovalRuntimeRejected, TypeError, ValueError) as exc:
        raise SignedApprovalSubmissionRejected(401, f"signed approval signature is invalid: {exc}") from None

    payload = envelope["payload"]
    _strict_object(payload, _PAYLOAD_KEYS, "payload")
    _strict_object(payload["author"], _ACTOR_KEYS, "author")
    _strict_object(payload["reviewer"], _ACTOR_KEYS, "reviewer")
    _strict_object(
        payload["request"],
        {"action", "resource_type", "resource_id", "sha256"},
        "request",
    )
    _strict_object(
        payload["effect"],
        {"action", "target_id", "target_sha256"},
        "effect",
    )
    _strict_object(
        payload["reviewer_authentication"],
        {"auth_time", "acr", "amr", "session_fingerprint"},
        "reviewer authentication",
    )
    _strict_object(payload["policy"], {"version", "sha256"}, "policy")
    _strict_object(payload["evidence"], {"tip_hash", "records"}, "evidence")
    _strict_object(payload["runtime"], {"source_commit"}, "runtime")
    _strict_object(
        payload["closure"],
        {"operational", "epistemic", "remedial"},
        "closure",
    )
    if not isinstance(payload["prior_approvers"], list):
        raise SignedApprovalSubmissionRejected(400, "signed approval prior_approvers must be an array")
    for index, actor in enumerate(payload["prior_approvers"]):
        _strict_object(actor, _ACTOR_KEYS, f"prior approver {index}")
    if not isinstance(payload["evidence"]["records"], list):
        raise SignedApprovalSubmissionRejected(400, "signed approval evidence records must be an array")
    for index, record in enumerate(payload["evidence"]["records"]):
        _strict_object(
            record,
            {"id", "sequence", "record_type", "record_hash"},
            f"evidence record {index}",
        )
    if (
        not isinstance(payload["reason"], str)
        or not payload["reason"].strip()
        or len(payload["reason"]) > _MAX_REASON_CHARS
    ):
        raise SignedApprovalSubmissionRejected(400, "signed approval reason is invalid")

    try:
        validate_approval_semantics(payload, now=current)
        if not approval_is_current(payload, now=current):
            raise ApprovalContractError("signed approval is expired or not yet valid")
    except ApprovalContractError as exc:
        raise SignedApprovalSubmissionRejected(400, f"signed approval contract is invalid: {exc}") from None

    if (
        payload["tenant_id"] != verified_subject.tenant_id
        or payload["request"]["action"] != "EXECUTE_PAID_ORDER"
        or payload["request"]["resource_type"] != "checkout_order"
        or payload["request"]["resource_id"] != order_id
        or payload["effect"]["action"] != "QUEUE_SINGLE_EXECUTION"
        or payload["effect"]["target_id"] != order_id
        or payload["effect"]["target_sha256"] != payload["request"]["sha256"]
        or payload["decision"] != "ALLOW"
        or payload["effect_authorized"] is not True
    ):
        raise SignedApprovalSubmissionRejected(
            403, "signed approval does not authorize this exact paid order effect"
        )

    current_source = runtime_source_commit()
    policy_version = os.getenv("OLA_APPROVAL_POLICY_VERSION", "")
    policy_sha256 = os.getenv("OLA_APPROVAL_POLICY_SHA256", "")
    if (
        not isinstance(current_source, str)
        or re.fullmatch(r"[0-9a-f]{40}", current_source) is None
        or payload["runtime"]["source_commit"] != current_source
        or not policy_version
        or re.fullmatch(r"[0-9a-f]{64}", policy_sha256) is None
        or payload["policy"]["version"] != policy_version
        or payload["policy"]["sha256"] != policy_sha256
    ):
        raise SignedApprovalSubmissionRejected(
            409, "signed approval source or policy binding is stale or unavailable"
        )

    try:
        _validate_live_reviewer_session(
            payload,
            verified_subject,
            fingerprint_key=fingerprint_key,
            fingerprint_key_id=fingerprint_key_id,
            now=current,
        )
        resolved_reviewer = resolve_human_gate_membership(
            db,
            verified_subject,
            resource_tenant_id=payload["tenant_id"],
            fingerprint_key=fingerprint_key,
            fingerprint_key_id=fingerprint_key_id,
            required_role="execution_approver",
        )
    except HumanGateMembershipError as exc:
        raise SignedApprovalSubmissionRejected(403, str(exc)) from None

    reviewer = payload["reviewer"]
    if (
        reviewer["principal_id"] != resolved_reviewer.principal_id
        or reviewer["tenant_id"] != resolved_reviewer.tenant_id
        or reviewer["issuer"] != resolved_reviewer.issuer
        or reviewer["subject_fingerprint"] != resolved_reviewer.subject_fingerprint
        or reviewer["fingerprint_key_id"] != resolved_reviewer.fingerprint_key_id
        or reviewer["role"] != resolved_reviewer.role
        or reviewer["membership_version"] != resolved_reviewer.membership_version
    ):
        raise SignedApprovalSubmissionRejected(
            403, "signed reviewer membership does not match the live OIDC membership"
        )

    begin_write_transaction(db, tenant_id=payload["tenant_id"])
    try:
        order, control, payment, checkout_proof, payment_proof, private_task, rows, records = _validate_paid_order(
            db,
            tenant_id=payload["tenant_id"],
            order_id=order_id,
            approver_id=resolved_reviewer.principal_id,
            tip_hash=payload["evidence"]["tip_hash"],
        )
    except ValueError as exc:
        raise SignedApprovalSubmissionRejected(
            getattr(exc, "code", 409), str(exc),
        ) from None

    if (
        order.request_hash != payload["request"]["sha256"]
        or hashlib.sha256(private_task.encode("utf-8")).hexdigest() != order.request_hash
        or payload["operation_id"] == order.id
    ):
        raise SignedApprovalSubmissionRejected(
            409, "signed approval request digest or operation binding is invalid"
        )
    if control.signed_approval_envelope_json or control.approval_record_hash:
        raise SignedApprovalSubmissionRejected(409, "order already has a signed or legacy approval")
    existing_job = db.scalar(
        select(CheckoutExecutionJob).where(CheckoutExecutionJob.order_id == order_id)
    )
    if existing_job is not None or db.get(CheckoutExecutionJob, payload["operation_id"]) is not None:
        raise SignedApprovalSubmissionRejected(409, "execution job already exists for this order or operation")

    author = payload["author"]
    author_membership = db.get(HumanGateMembership, control.requester_id)
    _actor_matches_membership(
        author, author_membership, tenant_id=order.tenant_id, role="requester",
    )
    if author["principal_id"] != control.requester_id:
        raise SignedApprovalSubmissionRejected(403, "signed author is not the original order requester")
    requester_key = db.get(ApiKey, control.requester_id)
    if requester_key is None or requester_key.tenant_id != order.tenant_id:
        raise SignedApprovalSubmissionRejected(403, "original requester principal mapping is unavailable")

    rows_by_id = {row["id"]: row for row in records}
    references = payload["evidence"]["records"]
    for ref in references:
        row = rows_by_id.get(ref["id"])
        if (
            row is None
            or row["seq"] != ref["sequence"]
            or row["record_type"] != ref["record_type"]
            or row["record_hash"] != ref["record_hash"]
        ):
            raise SignedApprovalSubmissionRejected(409, "signed approval evidence reference is stale or mismatched")
    if (
        not references
        or references[-1]["record_hash"] != payload["evidence"]["tip_hash"]
        or payload["evidence"]["tip_hash"] != records[-1]["record_hash"]
    ):
        raise SignedApprovalSubmissionRejected(409, "signed approval evidence tip is stale")

    checkout_refs = [ref for ref in references if ref["record_type"] == "stripe.checkout_created"]
    payment_refs = [ref for ref in references if ref["record_type"] == "stripe.payment_confirmed"]
    if (
        len(checkout_refs) != 1
        or len(payment_refs) != 1
        or checkout_refs[0]["id"] != checkout_proof["id"]
        or payment_refs[0]["id"] != payment_proof["id"]
        or checkout_refs[0]["sequence"] >= payment_refs[0]["sequence"]
    ):
        raise SignedApprovalSubmissionRejected(409, "signed approval does not bind the trusted checkout and payment records")

    approval_digest = signed_envelope_sha256(envelope)
    approved_at = int(current.timestamp())
    approval_payload = {
        "event": "human.revenue_execution_approval",
        "order_id": order.id,
        "tenant_id": order.tenant_id,
        "requester_id": control.requester_id,
        "approver_id": resolved_reviewer.principal_id,
        "approver_role": "execution_approver",
        "reason": payload["reason"],
        "checkout_session_id": order.stripe_session_id,
        "stripe_event_id": payment["event_id"],
        "checkout_evidence_id": checkout_proof["id"],
        "checkout_evidence_hash": checkout_proof["record_hash"],
        "payment_evidence_id": payment_proof["id"],
        "payment_evidence_hash": payment_proof["record_hash"],
        "request_hash": order.request_hash,
        "approved_tip_hash": payload["evidence"]["tip_hash"],
        "source_commit": current_source,
        "approved_at": approved_at,
        "decision": "APPROVED_FOR_EXECUTION",
        "execution_authorized": True,
        "deployment_authorized": False,
        "production_authorized": False,
        "signed_approval_envelope_sha256": approval_digest,
        "approval_id": payload["approval_id"],
        "operation_id": payload["operation_id"],
        "nonce": payload["nonce"],
    }
    approval_record = append_evidence_v4_locked(
        db,
        order.tenant_id,
        "human.revenue_execution_approval",
        approval_payload,
        producer_id="ola_runtime",
    )

    control.status = "APPROVED_FOR_EXECUTION"
    control.approver_id = resolved_reviewer.principal_id
    control.approval_reason = payload["reason"]
    control.approved_tip_hash = payload["evidence"]["tip_hash"]
    control.approval_record_hash = approval_record["record_hash"]
    control.approved_at = approved_at
    control.signed_approval_envelope_json = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    job = CheckoutExecutionJob(
        id=payload["operation_id"],
        tenant_id=order.tenant_id,
        order_id=order.id,
        approval_record_hash=approval_record["record_hash"],
        task=private_task,
        status="QUEUED",
        attempt_count=0,
    )
    db.add(job)
    db.flush()

    # Re-run exactly the same worker-side verifier against the just-appended
    # approval record before committing the approval/outbox transaction.
    updated_records = [*records, {
        "id": approval_record["id"],
        "tenant_id": order.tenant_id,
        "seq": approval_record["seq"],
        "record_type": "human.revenue_execution_approval",
        "prev_hash": payload["evidence"]["tip_hash"],
        "record_hash": approval_record["record_hash"],
        "payload_json": json.dumps(approval_payload, sort_keys=True, separators=(",", ":")),
    }]
    try:
        verify_paid_order_signed_approval(
            db,
            envelope_json=control.signed_approval_envelope_json,
            order=order,
            control=control,
            job=job,
            evidence_rows=updated_records,
            approval_evidence_payload=approval_payload,
            current_source_commit=current_source,
        )
    except SignedApprovalRuntimeRejected as exc:
        raise SignedApprovalSubmissionRejected(409, str(exc)) from None
    db.commit()
    return {
        "status": "APPROVED_FOR_EXECUTION",
        "order_id": order.id,
        "approval_record_id": approval_record["id"],
        "execution_job_id": job.id,
        "execution": "QUEUED",
        "execution_job_status": "QUEUED",
        "next_gate": "EXECUTION_DISPATCH",
        "deployment_authorized": False,
        "production_authorized": False,
    }
