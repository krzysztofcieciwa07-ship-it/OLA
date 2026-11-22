"""Fail-closed Signed Approval v1 verifier at the paid-order effect boundary.

This module verifies a stored, externally signed envelope. It never creates a
signature, trusts keys supplied by the caller, performs OIDC network discovery,
consumes a nonce, commits a transaction, or runs an external effect.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from .approval_contract_v1 import (
    ApprovalContractError,
    approval_is_current,
    validate_approval_semantics,
    verify_signed_approval_envelope,
)
from .database import set_human_gate_tenant_scope
from .models import ApiKey, HumanGateMembership


class SignedApprovalRuntimeRejected(ValueError):
    """A stored signed approval is not currently valid for this paid-order job."""


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
_ALLOWED_REVIEWER_AMR = frozenset({"webauthn", "mfa"})


def _exact_keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != expected:
        raise SignedApprovalRuntimeRejected(f"signed approval {name} shape is invalid")


def _trusted_public_keys():
    raw = os.getenv("OLA_APPROVAL_ED25519_TRUSTED_KEYS_JSON", "")
    if not raw:
        raise SignedApprovalRuntimeRejected("signed approval Ed25519 trust store is not configured")
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        raise SignedApprovalRuntimeRejected("signed approval Ed25519 trust store is invalid") from None
    if not isinstance(document, dict) or not document or len(document) > 16:
        raise SignedApprovalRuntimeRejected("signed approval Ed25519 trust store shape is invalid")
    result = {}
    for key_id, encoded in document.items():
        if (
            not isinstance(key_id, str)
            or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key_id) is None
            or not isinstance(encoded, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded) is None
        ):
            raise SignedApprovalRuntimeRejected("signed approval trusted key entry is invalid")
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=")
        except (ValueError, base64.binascii.Error):
            raise SignedApprovalRuntimeRejected("signed approval trusted public key is invalid") from None
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != encoded:
            raise SignedApprovalRuntimeRejected("signed approval trusted public key must be canonical 32-byte Ed25519")
        result[key_id] = decoded
    return result


def signed_envelope_sha256(envelope: dict) -> str:
    try:
        encoded = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise SignedApprovalRuntimeRejected("signed approval envelope cannot be serialized") from None
    if len(encoded) > 66_000:
        raise SignedApprovalRuntimeRejected("signed approval envelope exceeds size limit")
    return hashlib.sha256(encoded).hexdigest()


def _current_membership(db, actor, *, expected_tenant, expected_role, label):
    # RLS is transaction-scoped: establish the resource tenant before the
    # primary-key lookup, then keep the explicit row/actor tenant comparisons.
    try:
        set_human_gate_tenant_scope(db, expected_tenant)
    except (ValueError, RuntimeError):
        raise SignedApprovalRuntimeRejected(
            "current Human Gate tenant RLS scope could not be established"
        ) from None
    row = db.get(HumanGateMembership, actor["principal_id"])
    if (
        row is None
        or row.id != actor["principal_id"]
        or row.tenant_id != expected_tenant
        or actor["tenant_id"] != expected_tenant
        or row.issuer != actor["issuer"]
        or row.subject_fingerprint != actor["subject_fingerprint"]
        or row.fingerprint_key_id != actor["fingerprint_key_id"]
        or row.role != expected_role
        or actor["role"] != expected_role
        or row.membership_version != actor["membership_version"]
        or row.active is not True
        or row.revoked_at is not None
    ):
        raise SignedApprovalRuntimeRejected(
            f"current {label} tenant membership is missing, changed, revoked or has the wrong role"
        )
    return row


def verify_paid_order_signed_approval(
    db,
    *,
    envelope_json: str | None,
    order,
    control,
    job,
    evidence_rows: list[dict],
    approval_evidence_payload: dict,
    current_source_commit: str,
):
    """Verify one exact paid-order effect against the current persisted state."""
    if not isinstance(envelope_json, str) or not envelope_json:
        raise SignedApprovalRuntimeRejected(
            "legacy API-key approval is not an execution authorization; signed Human Gate envelope is required"
        )
    if len(envelope_json.encode("utf-8")) > 66_000:
        raise SignedApprovalRuntimeRejected("stored signed approval envelope exceeds size limit")
    try:
        envelope = json.loads(envelope_json)
    except (ValueError, TypeError):
        raise SignedApprovalRuntimeRejected("stored signed approval envelope is invalid JSON") from None

    try:
        verify_signed_approval_envelope(envelope, _trusted_public_keys())
        payload = envelope["payload"]
        _exact_keys(payload, _PAYLOAD_KEYS, "payload")
        _exact_keys(payload["author"], _ACTOR_KEYS, "author")
        _exact_keys(payload["reviewer"], _ACTOR_KEYS, "reviewer")
        _exact_keys(payload["request"], {"action", "resource_type", "resource_id", "sha256"}, "request")
        _exact_keys(payload["effect"], {"action", "target_id", "target_sha256"}, "effect")
        _exact_keys(
            payload["reviewer_authentication"],
            {"auth_time", "acr", "amr", "session_fingerprint"},
            "reviewer authentication",
        )
        _exact_keys(payload["policy"], {"version", "sha256"}, "policy")
        _exact_keys(payload["evidence"], {"tip_hash", "records"}, "evidence")
        _exact_keys(payload["runtime"], {"source_commit"}, "runtime")
        _exact_keys(payload["closure"], {"operational", "epistemic", "remedial"}, "closure")
        for index, record in enumerate(payload["evidence"]["records"]):
            _exact_keys(record, {"id", "sequence", "record_type", "record_hash"}, f"evidence record {index}")
        validate_approval_semantics(payload)
    except (ApprovalContractError, KeyError, TypeError, ValueError) as exc:
        raise SignedApprovalRuntimeRejected(f"signed approval contract validation failed: {exc}") from None

    if not approval_is_current(payload):
        raise SignedApprovalRuntimeRejected("signed Human Gate approval is expired or not yet valid")
    if payload.get("decision") != "ALLOW" or payload.get("effect_authorized") is not True:
        raise SignedApprovalRuntimeRejected("signed Human Gate approval does not authorize an effect")

    tenant_id = order.tenant_id
    request = payload["request"]
    effect = payload["effect"]
    if (
        payload["tenant_id"] != tenant_id
        or request["action"] != "EXECUTE_PAID_ORDER"
        or request["resource_type"] != "checkout_order"
        or request["resource_id"] != order.id
        or request["sha256"] != order.request_hash
        or effect["action"] != "QUEUE_SINGLE_EXECUTION"
        or effect["target_id"] != order.id
        or effect["target_sha256"] != order.request_hash
        or payload["operation_id"] != job.id
    ):
        raise SignedApprovalRuntimeRejected("signed approval is bound to a different tenant, order, task or operation")

    if payload["runtime"]["source_commit"] != current_source_commit:
        raise SignedApprovalRuntimeRejected("signed approval source commit is stale or mismatched")
    required_acr = os.getenv("OLA_APPROVAL_REQUIRED_ACR", "")
    required_amr = {
        item.strip() for item in os.getenv("OLA_APPROVAL_REQUIRED_AMR", "").split(",")
        if item.strip()
    }
    if (
        not required_acr
        or not required_amr
        or payload["reviewer_authentication"]["acr"] != required_acr
        or not required_amr.issubset(set(payload["reviewer_authentication"]["amr"]))
    ):
        raise SignedApprovalRuntimeRejected("signed approval reviewer step-up authentication does not meet current policy")
    expected_policy_version = os.getenv("OLA_APPROVAL_POLICY_VERSION", "")
    expected_policy_sha256 = os.getenv("OLA_APPROVAL_POLICY_SHA256", "")
    if (
        not expected_policy_version
        or re.fullmatch(r"[0-9a-f]{64}", expected_policy_sha256) is None
        or payload["policy"]["version"] != expected_policy_version
        or payload["policy"]["sha256"] != expected_policy_sha256
    ):
        raise SignedApprovalRuntimeRejected("signed approval policy is not the current configured policy")

    author = payload["author"]
    reviewer = payload["reviewer"]
    if author["principal_id"] != control.requester_id:
        raise SignedApprovalRuntimeRejected("signed approval author is not the original checkout requester")
    if reviewer["principal_id"] != control.approver_id:
        raise SignedApprovalRuntimeRejected("signed approval reviewer does not match the persisted approver")
    _current_membership(
        db, author, expected_tenant=tenant_id, expected_role="requester", label="author",
    )
    reviewer_membership = _current_membership(
        db, reviewer, expected_tenant=tenant_id,
        expected_role="execution_approver", label="reviewer",
    )
    if reviewer_membership.id == author["principal_id"]:
        raise SignedApprovalRuntimeRejected("checkout requester cannot approve their own order")
    approver_key = db.get(ApiKey, control.approver_id)
    if approver_key is None or approver_key.tenant_id != tenant_id or approver_key.role != "execution_approver":
        raise SignedApprovalRuntimeRejected("persisted technical approver mapping is not valid")

    rows_by_id = {row["id"]: row for row in evidence_rows}
    references = payload["evidence"]["records"]
    for reference in references:
        row = rows_by_id.get(reference["id"])
        if (
            row is None
            or row["tenant_id"] != tenant_id
            or row["seq"] != reference["sequence"]
            or row["record_type"] != reference["record_type"]
            or row["record_hash"] != reference["record_hash"]
        ):
            raise SignedApprovalRuntimeRejected("signed approval evidence reference is missing or changed")
    if not references or references[-1]["record_hash"] != payload["evidence"]["tip_hash"]:
        raise SignedApprovalRuntimeRejected("signed approval evidence tip does not match its final reference")
    checkout_refs = [row for row in references if row["record_type"] == "stripe.checkout_created"]
    payment_refs = [row for row in references if row["record_type"] == "stripe.payment_confirmed"]
    if len(checkout_refs) != 1 or len(payment_refs) != 1:
        raise SignedApprovalRuntimeRejected("signed approval must bind exactly one trusted checkout and payment record")
    if checkout_refs[0]["sequence"] >= payment_refs[0]["sequence"]:
        raise SignedApprovalRuntimeRejected("signed approval checkout evidence must precede payment evidence")
    if not any(
        row["record_type"] == "stripe.checkout_created" and row["id"] == checkout_refs[0]["id"]
        for row in evidence_rows
    ):
        raise SignedApprovalRuntimeRejected("trusted checkout evidence is unavailable")
    if not any(
        row["record_type"] == "stripe.payment_confirmed" and row["id"] == payment_refs[0]["id"]
        for row in evidence_rows
    ):
        raise SignedApprovalRuntimeRejected("trusted payment evidence is unavailable")

    envelope_digest = signed_envelope_sha256(envelope)
    approval_record_rows = [
        row for row in evidence_rows
        if row["record_hash"] == job.approval_record_hash
    ]
    if (
        len(approval_record_rows) != 1
        or approval_record_rows[0]["prev_hash"] != payload["evidence"]["tip_hash"]
        or not evidence_rows
        or evidence_rows[-1]["id"] != approval_record_rows[0]["id"]
        or evidence_rows[-1]["record_hash"] != job.approval_record_hash
    ):
        raise SignedApprovalRuntimeRejected(
            "signed approval evidence is stale: approval record is not the current tenant evidence tip"
        )
    if not isinstance(approval_evidence_payload, dict):
        raise SignedApprovalRuntimeRejected("trusted approval evidence payload is invalid")
    if (
        approval_evidence_payload.get("checkout_evidence_id") != checkout_refs[0]["id"]
        or approval_evidence_payload.get("checkout_evidence_hash") != checkout_refs[0]["record_hash"]
        or approval_evidence_payload.get("payment_evidence_id") != payment_refs[0]["id"]
        or approval_evidence_payload.get("payment_evidence_hash") != payment_refs[0]["record_hash"]
        or approval_evidence_payload.get("approved_tip_hash") != payload["evidence"]["tip_hash"]
        or approval_evidence_payload.get("requester_id") != author["principal_id"]
        or approval_evidence_payload.get("approver_id") != reviewer["principal_id"]
        or approval_evidence_payload.get("source_commit") != current_source_commit
        or control.approved_tip_hash != payload["evidence"]["tip_hash"]
    ):
        raise SignedApprovalRuntimeRejected("signed approval evidence references do not match the approved checkout/payment chain")
    if (
        not isinstance(approval_evidence_payload, dict)
        or approval_evidence_payload.get("signed_approval_envelope_sha256") != envelope_digest
        or approval_evidence_payload.get("approval_id") != payload["approval_id"]
        or approval_evidence_payload.get("operation_id") != payload["operation_id"]
        or approval_evidence_payload.get("nonce") != payload["nonce"]
        or approval_evidence_payload.get("order_id") != order.id
        or approval_evidence_payload.get("tenant_id") != tenant_id
        or approval_evidence_payload.get("request_hash") != order.request_hash
        or approval_evidence_payload.get("decision") != "APPROVED_FOR_EXECUTION"
        or approval_evidence_payload.get("execution_authorized") is not True
        or approval_evidence_payload.get("deployment_authorized") is not False
        or approval_evidence_payload.get("production_authorized") is not False
    ):
        raise SignedApprovalRuntimeRejected("trusted approval evidence does not bind the signed envelope")
    return payload, envelope_digest
