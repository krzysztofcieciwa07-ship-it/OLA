"""Recovery never re-executes a paid task or skips independent delivery review."""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import agent_runtime, stripe_webhook
from app.database import SessionLocal, append_evidence_atomic
from app.hashchain import verify_chain, trusted_record
from app.main import app
from app.models import EvidenceRecord, StripeCheckoutClaim, StripeEvent, Tenant
from app.stripe_recovery import PENDING_REVIEW, RECOVERY_RECORD_TYPE, reconcile_checkout


WEBHOOK_SECRET = "whsec_recovery_test_only"


@pytest.fixture
def tenant_id(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    monkeypatch.setattr(agent_runtime, "_invoke_llm", lambda *_args: None)
    tenant = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant, name="recovery-test"))
        db.commit()
    return tenant


def _signed_event(tenant_id, session_id=None):
    session_id = session_id or "cs_test_" + uuid.uuid4().hex
    event_id = "evt_test_" + uuid.uuid4().hex
    event = {
        "id": event_id, "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id, "status": "complete", "payment_status": "paid",
            "currency": "eur", "amount_total": 9900,
            "metadata": {"tenant_id": tenant_id, "offer": "ola-execution-audit",
                         "product": "OLA Execution Audit", "task": "Audit this workflow"},
        }},
    }
    raw = json.dumps(event, sort_keys=True).encode()
    timestamp = int(time.time())
    digest = hmac.new(WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + raw,
                      hashlib.sha256).hexdigest()
    return session_id, event_id, raw, f"t={timestamp},v1={digest}"


def _records(tenant_id):
    with SessionLocal() as db:
        return db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
        ).order_by(EvidenceRecord.seq)).all()


def _chain_ok(rows):
    return verify_chain([{
        "tenant_id": row.tenant_id, "seq": row.seq,
        "prev_hash": row.prev_hash, "record_hash": row.record_hash,
        "record_type": row.record_type, "payload_json": row.payload_json,
    } for row in rows])


def _simulate_crash_after_completed_local_evidence(tenant_id, monkeypatch):
    """Construct a historical crash snapshot: past runtime already completed.

    The current signed webhook must NEVER execute. We seed the persisted old
    PROCESSING->FAILED state and independent existing agent evidence directly,
    so recovery tests still prove old transactions cannot be rerun or forged.
    """
    session_id, event_id, _raw, _signature = _signed_event(tenant_id)
    task = "Audit this workflow"
    with SessionLocal() as db:
        db.add(StripeCheckoutClaim(session_id=session_id, tenant_id=tenant_id,
                                   event_id=event_id, task=task, status="FAILED"))
        db.add(StripeEvent(id=str(uuid.uuid4()), event_id=event_id,
                           status="FAILED", task=task))
        db.commit()
    payment_id = append_evidence_atomic(tenant_id, "stripe.payment_confirmed", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "offer": "ola-execution-audit", "product": "OLA Execution Audit",
        "amount_total": 9900, "currency": "eur", "task": task,
    })["id"]
    actual = agent_runtime.run_agent_task(tenant_id, task)
    assert actual["status"] == "VERIFIED"
    append_evidence_atomic(tenant_id, "stripe.ola_execution_recorded", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "ola_run_id": actual["run_id"], "ola_status": actual["status"],
        "delivery_status": PENDING_REVIEW,
        "ola_final_result": actual.get("final_result"),
        "payment_evidence_id": payment_id,
    })
    with SessionLocal() as db:
        claim = db.get(StripeCheckoutClaim, session_id)
        event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert claim.status == event.status == "FAILED"
        assert claim.result_json is None and event.result_json is None
    return session_id, event_id


@pytest.mark.parametrize("uncertain_status", ["FAILED", "PROCESSING"])
def test_verified_local_crash_recovers_only_to_pending_review(
    tenant_id, monkeypatch, uncertain_status,
):
    session_id, event_id = _simulate_crash_after_completed_local_evidence(
        tenant_id, monkeypatch)
    if uncertain_status == "PROCESSING":
        # Simulate a process killed after its final evidence append, before
        # the webhook was able to update the mutable state rows.
        with SessionLocal() as db:
            db.get(StripeCheckoutClaim, session_id).status = "PROCESSING"
            db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id)).status = "PROCESSING"
            db.commit()
    before = _records(tenant_id)
    assert _chain_ok(before) == (True, "ok")

    inspected = reconcile_checkout(session_id)
    assert inspected["status"] == "RECOVERABLE_PENDING_REVIEW"
    assert inspected["applied"] is False
    assert len(_records(tenant_id)) == len(before)

    recovered = reconcile_checkout(session_id, apply=True)
    assert recovered["status"] == "RECORDED_PENDING_REVIEW"
    assert recovered["applied"] is True
    with SessionLocal() as db:
        claim = db.get(StripeCheckoutClaim, session_id)
        event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
        assert claim.status == event.status == PENDING_REVIEW
        assert claim.result_json == event.result_json
        result = json.loads(claim.result_json)
        assert result["status"] == PENDING_REVIEW
        assert result["checkout_session_id"] == session_id
        assert result["ola_run_id"] == recovered["run_id"]
        assert len(result["ola_evidence_ids"]) == len(agent_runtime.AGENT_ROLES)

    after = _records(tenant_id)
    assert len(after) == len(before) + 1
    assert after[-1].record_type == RECOVERY_RECORD_TYPE
    assert trusted_record({"record_type": after[-1].record_type,
                           "payload_json": after[-1].payload_json})
    assert _chain_ok(after) == (True, "ok")
    repeated = reconcile_checkout(session_id, apply=True)
    assert repeated["applied"] is False
    assert len(_records(tenant_id)) == len(after)


def test_webhook_redelivery_after_recovery_never_executes_again(tenant_id, monkeypatch):
    session_id, _ = _simulate_crash_after_completed_local_evidence(tenant_id, monkeypatch)
    assert reconcile_checkout(session_id, apply=True)["status"] == "RECORDED_PENDING_REVIEW"
    before = len(_records(tenant_id))

    def forbidden_runtime(*_args):
        pytest.fail("recovery must never re-execute this paid order")

    monkeypatch.setattr(stripe_webhook, "run_agent_task", forbidden_runtime)
    _, _, raw, signature = _signed_event(tenant_id, session_id=session_id)
    response = TestClient(app).post("/stripe/webhook", content=raw,
                                    headers={"Stripe-Signature": signature})
    assert response.status_code == 200
    assert response.json()["status"] == PENDING_REVIEW
    assert len(_records(tenant_id)) == before


def test_no_completion_proof_never_enables_rerun(tenant_id):
    session_id = "cs_test_" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(StripeCheckoutClaim(session_id=session_id, tenant_id=tenant_id,
                                   event_id="evt_missing", task="Audit this workflow",
                                   status="PROCESSING"))
        db.add(StripeEvent(id=str(uuid.uuid4()), event_id="evt_missing",
                           status="PROCESSING", task="Audit this workflow"))
        db.commit()
    inspected = reconcile_checkout(session_id, apply=True)
    assert inspected["status"] == "UNCERTAIN"
    assert inspected["applied"] is False
    with SessionLocal() as db:
        assert db.get(StripeCheckoutClaim, session_id).status == "PROCESSING"


def test_full_agent_run_without_checkout_completion_link_stays_uncertain(tenant_id):
    session_id = "cs_test_" + uuid.uuid4().hex
    event_id = "evt_test_" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(StripeCheckoutClaim(session_id=session_id, tenant_id=tenant_id,
                                   event_id=event_id, task="Audit this workflow",
                                   status="FAILED"))
        db.add(StripeEvent(id=str(uuid.uuid4()), event_id=event_id,
                           status="FAILED", task="Audit this workflow"))
        db.commit()
    append_evidence_atomic(tenant_id, "stripe.payment_confirmed", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "offer": "ola-execution-audit", "product": "OLA Execution Audit",
        "amount_total": 9900, "currency": "eur", "task": "Audit this workflow",
    })
    agent_runtime.run_agent_task(tenant_id, "Audit this workflow")
    status = reconcile_checkout(session_id, apply=True)
    assert status["status"] == "UNCERTAIN"
    assert status["applied"] is False


def test_publicly_submitted_checkout_completion_cannot_authorize_recovery(tenant_id):
    session_id = "cs_test_" + uuid.uuid4().hex
    event_id = "evt_test_" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(StripeCheckoutClaim(session_id=session_id, tenant_id=tenant_id,
                                   event_id=event_id, task="Audit this workflow",
                                   status="PROCESSING"))
        db.add(StripeEvent(id=str(uuid.uuid4()), event_id=event_id,
                           status="PROCESSING", task="Audit this workflow"))
        db.commit()
    payment_id = append_evidence_atomic(tenant_id, "stripe.payment_confirmed", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "offer": "ola-execution-audit", "product": "OLA Execution Audit",
        "amount_total": 9900, "currency": "eur", "task": "Audit this workflow",
    })["id"]
    agent_run = agent_runtime.run_agent_task(tenant_id, "Audit this workflow")
    append_evidence_atomic(tenant_id, "stripe.ola_execution_recorded", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "ola_run_id": agent_run["run_id"], "ola_status": "VERIFIED",
        "delivery_status": PENDING_REVIEW, "payment_evidence_id": payment_id,
    }, producer_id="tenant_api")
    status = reconcile_checkout(session_id, apply=True)
    assert status["status"] == "UNCERTAIN"
    assert status["applied"] is False


def test_unverifiable_agent_run_cannot_be_restored_from_completion_label(tenant_id):
    session_id = "cs_test_" + uuid.uuid4().hex
    event_id = "evt_test_" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(StripeCheckoutClaim(session_id=session_id, tenant_id=tenant_id,
                                   event_id=event_id, task="Audit this workflow",
                                   status="FAILED"))
        db.add(StripeEvent(id=str(uuid.uuid4()), event_id=event_id,
                           status="FAILED", task="Audit this workflow"))
        db.commit()
    payment_id = append_evidence_atomic(tenant_id, "stripe.payment_confirmed", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "offer": "ola-execution-audit", "product": "OLA Execution Audit",
        "amount_total": 9900, "currency": "eur", "task": "Audit this workflow",
    })["id"]
    append_evidence_atomic(tenant_id, "stripe.ola_execution_recorded", {
        "stripe_event_id": event_id, "checkout_session_id": session_id,
        "ola_run_id": "run-without-agent-proof", "ola_status": "VERIFIED",
        "delivery_status": PENDING_REVIEW, "payment_evidence_id": payment_id,
    })
    result = reconcile_checkout(session_id, apply=True)
    assert result["status"] == "UNCERTAIN"
    assert result["applied"] is False


def test_invalid_chain_blocks_any_recovery(tenant_id, monkeypatch):
    session_id, _ = _simulate_crash_after_completed_local_evidence(tenant_id, monkeypatch)
    with SessionLocal() as db:
        end = db.scalar(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id,
        ).order_by(EvidenceRecord.seq.desc()))
        db.add(EvidenceRecord(
            id=str(uuid.uuid4()), tenant_id=tenant_id, seq=end.seq + 1,
            record_type="dummy", payload_json="{}",
            prev_hash=end.record_hash, record_hash="f" * 64,
        ))
        db.commit()
    status = reconcile_checkout(session_id, apply=True)
    assert status["status"] == "BLOCKED"
    assert status["reason"] == "invalid_evidence_chain"
    assert status["applied"] is False


def test_recovery_cli_has_no_automatic_apply_on_unknown_order(tenant_id):
    result = subprocess.run(
        [sys.executable, "-m", "scripts.reconcile_stripe_orders",
         "cs_test_not_registered"], text=True, capture_output=True,
    )
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "BLOCKED"
    assert output["applied"] is False


def test_recovery_cli_requires_explicit_db_path_for_any_write(monkeypatch):
    environment = dict(os.environ)
    environment.pop("OLA_EG_DB_PATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.reconcile_stripe_orders",
         "cs_test_missing", "--apply"], text=True, capture_output=True,
        env=environment,
    )
    assert result.returncode == 2
    assert "OLA_EG_DB_PATH" in result.stderr
