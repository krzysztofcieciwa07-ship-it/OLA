"""Fail-closed reconciliation of uncertain Stripe orders; never rerun an agent.

Only a completed, trusted local evidence trail can restore an order to
PENDING_INDEPENDENT_VERIFICATION. This is not Stripe re-verification, independent
human approval, customer delivery, or permission to execute the task again.
"""

import json
import uuid

from sqlalchemy import select

from .agent_runtime import AGENT_ROLES, verify_agent_run
from .database import SessionLocal
from .hashchain import (
    EVIDENCE_META_KEY, GENESIS_HASH, canonical_json, compute_record_hash_v2,
    sealed_payload_json, verify_chain,
)
from .models import EvidenceRecord, StripeCheckoutClaim, StripeEvent
from .stripe_webhook import OLA_OFFER, OLA_PRODUCT


UNCERTAIN = {"PROCESSING", "FAILED"}
PENDING_REVIEW = "PENDING_INDEPENDENT_VERIFICATION"
RECOVERY_RECORD_TYPE = "execution.stripe_order_reconciled"


def _trusted_runtime_record(row, payload):
    return payload.get(EVIDENCE_META_KEY) == {
        "version": 2, "record_type": row.record_type, "producer": "ola_runtime",
    }


def _inspect(db, session_id):
    report = {"checkout_session_id": session_id, "status": "BLOCKED"}
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        return {**report, "reason": "invalid_checkout_session_id"}, None

    claim = db.get(StripeCheckoutClaim, session_id)
    if claim is None:
        return {**report, "reason": "no_durable_checkout_claim"}, None

    report["claim_status"] = claim.status
    event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == claim.event_id))
    if event is None or event.task != claim.task or event.status != claim.status:
        return {**report, "reason": "claim_event_state_mismatch"}, None
    if claim.status not in UNCERTAIN:
        return {**report, "reason": "order_not_in_uncertain_state"}, None
    if claim.result_json or event.result_json:
        return {**report, "reason": "unexpected_stored_result"}, None

    rows = db.scalars(select(EvidenceRecord).where(
        EvidenceRecord.tenant_id == claim.tenant_id,
    ).order_by(EvidenceRecord.seq)).all()
    valid, chain_reason = verify_chain([{
        "tenant_id": row.tenant_id, "seq": row.seq,
        "prev_hash": row.prev_hash, "record_hash": row.record_hash,
        "record_type": row.record_type, "payload_json": row.payload_json,
    } for row in rows])
    if not valid:
        return {**report, "reason": "invalid_evidence_chain", "detail": chain_reason}, None

    parsed = [(row, json.loads(row.payload_json)) for row in rows]
    payments = [(row, value) for row, value in parsed
                if row.record_type == "stripe.payment_confirmed"
                and _trusted_runtime_record(row, value)
                and value.get("checkout_session_id") == session_id
                and value.get("stripe_event_id") == claim.event_id]
    completed = [(row, value) for row, value in parsed
                 if row.record_type == "stripe.ola_execution_recorded"
                 and _trusted_runtime_record(row, value)
                 and value.get("checkout_session_id") == session_id
                 and value.get("stripe_event_id") == claim.event_id]
    if len(payments) != 1 or len(completed) != 1:
        return {**report, "status": "UNCERTAIN", "reason": "missing_or_ambiguous_execution_proof"}, None

    payment_row, payment = payments[0]
    completed_row, execution = completed[0]
    run_id = execution.get("ola_run_id")
    if (payment_row.seq >= completed_row.seq
            or payment.get("task") != claim.task
            or payment.get("offer") != OLA_OFFER
            or payment.get("product") != OLA_PRODUCT
            or payment.get("amount_total") != 9900
            or payment.get("currency") != "eur"
            or not isinstance(run_id, str) or not run_id
            or execution.get("payment_evidence_id") != payment_row.id
            or execution.get("ola_status") != "VERIFIED"
            or execution.get("delivery_status") != PENDING_REVIEW):
        return {**report, "reason": "execution_payment_binding_mismatch"}, None

    # A run must not be used as proof for more than one Checkout Session.
    completions_for_run = [(row, value) for row, value in parsed
                           if row.record_type == "stripe.ola_execution_recorded"
                           and _trusted_runtime_record(row, value)
                           and value.get("ola_run_id") == run_id]
    if len(completions_for_run) != 1:
        return {**report, "reason": "reused_or_ambiguous_run_id"}, None

    run_rows = [(row, value) for row, value in parsed
                if row.record_type.startswith("agent.") and value.get("run_id") == run_id]
    if (len(run_rows) != len(AGENT_ROLES)
            or any(value.get("task") != claim.task
                   or not payment_row.seq < row.seq < completed_row.seq
                   for row, value in run_rows)):
        return {**report, "status": "UNCERTAIN", "reason": "agent_run_not_bound_to_order"}, None

    verification = verify_agent_run(claim.tenant_id, run_id)
    if verification.get("status") != "VERIFIED":
        return {**report, "reason": "agent_run_not_verified"}, None

    recovered = {
        "status": PENDING_REVIEW,
        "event_id": claim.event_id,
        "checkout_session_id": session_id,
        "payment": "CONFIRMED",
        "ola_status": "VERIFIED",
        "ola_run_id": run_id,
        "ola_final_result": execution.get("ola_final_result"),
        "payment_evidence_id": payment_row.id,
        "ola_evidence_ids": [row.id for row, _ in run_rows],
    }
    return {
        **report, "status": "RECOVERABLE_PENDING_REVIEW",
        "reason": "trusted_checkout_and_agent_evidence_verified",
        "run_id": run_id,
        "payment_evidence_id": payment_row.id,
        "execution_evidence_id": completed_row.id,
    }, recovered


def reconcile_checkout(session_id, *, apply=False):
    """Inspect by default; --apply only restores PENDING, never executes.

    When applying, use the same BEGIN IMMEDIATE transaction for proof inspection,
    append-only recovery evidence and the two mutable status updates.
    """
    with SessionLocal() as db:
        if apply:
            if db.bind.dialect.name != "sqlite":
                return {"checkout_session_id": session_id, "status": "BLOCKED",
                        "reason": "atomic_recovery_unavailable"}
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        report, result = _inspect(db, session_id)
        if not apply or result is None:
            return {**report, "applied": False}

        claim = db.get(StripeCheckoutClaim, session_id)
        event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == claim.event_id))
        payload = {
            "checkout_session_id": session_id, "stripe_event_id": claim.event_id,
            "run_id": result["ola_run_id"], "previous_status": claim.status,
            "decision": PENDING_REVIEW,
            "source_evidence_ids": [report["payment_evidence_id"], report["execution_evidence_id"]],
            "execution_repeated": False,
        }
        payload_json = sealed_payload_json(RECOVERY_RECORD_TYPE, payload)
        latest = db.scalar(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == claim.tenant_id,
        ).order_by(EvidenceRecord.seq.desc()))
        seq = 0 if latest is None else latest.seq + 1
        predecessor = GENESIS_HASH if latest is None else latest.record_hash
        record = EvidenceRecord(
            id=str(uuid.uuid4()), tenant_id=claim.tenant_id, seq=seq,
            record_type=RECOVERY_RECORD_TYPE, payload_json=payload_json,
            prev_hash=predecessor,
            record_hash=compute_record_hash_v2(
                claim.tenant_id, seq, predecessor, RECOVERY_RECORD_TYPE,
                "ola_runtime", payload_json,
            ),
        )
        db.add(record)
        claim.status = event.status = PENDING_REVIEW
        claim.result_json = event.result_json = canonical_json(result)
        event.run_id = result["ola_run_id"]
        db.commit()
        return {**report, "status": "RECORDED_PENDING_REVIEW",
                "reason": "local_execution_reconciled_no_delivery",
                "recovery_evidence_id": record.id, "applied": True}
