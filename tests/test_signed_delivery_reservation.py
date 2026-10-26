"""Signed, one-shot operator delivery reservation; never send customer data.

Synthetic Ed25519 signers are used only inside these tests, not production.
"""
import base64
import hashlib
import json
import os
import sys
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import agent_runtime
from app.database import SessionLocal, append_evidence_atomic
from app.fulfillment_release import reserve_delivery
from app.hashchain import canonical_json, verify_chain
from app.main import app
from app.models import EvidenceRecord, StripeCheckoutClaim, StripeEvent
from tests.test_stripe_webhook_flow import _signed_event, tenant_id


def _key_pair(tmp_path, label):
    private = tmp_path / (label + "-private.pem")
    public = tmp_path / (label + "-public.pem")
    subprocess.run(["openssl", "genpkey", "-algorithm", "Ed25519",
                    "-out", str(private)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout",
                    "-out", str(public)], check=True, capture_output=True)
    return private, public


def _sign(tmp_path, private, role, manifest):
    raw = canonical_json({
        "domain": "OLA-ORDER-DELIVERY-RELEASE-V1",
        "role": role,
        "manifest": manifest,
    }).encode("utf-8")
    message = tmp_path / (role + "-message.bin")
    sig = tmp_path / (role + "-signature.bin")
    message.write_bytes(raw)
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(private),
                    "-rawin", "-in", str(message), "-out", str(sig)],
                   check=True, capture_output=True)
    return base64.b64encode(sig.read_bytes()).decode("ascii")


def _review_keys(tmp_path, monkeypatch):
    igor_private, igor_public = _key_pair(tmp_path, "igor")
    owner_private, owner_public = _key_pair(tmp_path, "owner")
    monkeypatch.setenv("OLA_IGOR_PUBKEY_SHA256", hashlib.sha256(
        igor_public.read_bytes()).hexdigest())
    monkeypatch.setenv("OLA_OWNER_PUBKEY_SHA256", hashlib.sha256(
        owner_public.read_bytes()).hexdigest())
    monkeypatch.setenv("OLA_RELEASE_SOURCE_SHA", "a" * 40)
    return (igor_private, igor_public), (owner_private, owner_public)


def _make_order(tenant_id, monkeypatch, *, execution_proven=False):
    """Persist a real synthetic signed webhook into the existing order tables."""
    monkeypatch.setenv("OLA_LLM_PROVIDER", "none")
    monkeypatch.setenv("OLA_LLM_MODE", "deterministic")
    event_id, payload, signature = _signed_event(tenant_id)
    response = TestClient(app).post(
        "/stripe/webhook", content=payload,
        headers={"Stripe-Signature": signature},
    )
    assert response.status_code == 200, response.text
    session_id = json.loads(payload)["data"]["object"]["id"]
    assert response.json()["status"] == "PENDING_HUMAN_AUTHORIZATION"
    if execution_proven:
        # A separate, trusted runtime run is seeded to exercise historical
        # already-executed orders. Nothing is executed by the webhook itself.
        agent = agent_runtime.run_agent_task(tenant_id, "Audit this workflow")
        assert agent["status"] == "VERIFIED"
        append_evidence_atomic(tenant_id, "stripe.ola_execution_recorded", {
            "stripe_event_id": event_id,
            "checkout_session_id": session_id,
            "ola_run_id": agent["run_id"],
            "ola_status": "VERIFIED",
            "delivery_status": "PENDING_INDEPENDENT_VERIFICATION",
            "payment_evidence_id": response.json()["payment_evidence_id"],
        })
        with SessionLocal() as db:
            claim = db.get(StripeCheckoutClaim, session_id)
            event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == event_id))
            claim.status = event.status = "PENDING_INDEPENDENT_VERIFICATION"
            event.run_id = agent["run_id"]
            data = {
                "status": "PENDING_INDEPENDENT_VERIFICATION",
                "checkout_session_id": session_id, "event_id": event_id,
                "ola_run_id": agent["run_id"], "payment": "CONFIRMED",
                "payment_evidence_id": response.json()["payment_evidence_id"],
            }
            claim.result_json = event.result_json = canonical_json(data)
            db.commit()
        run_id = agent["run_id"]
    else:
        run_id = "unverified-run"
    with SessionLocal() as db:
        last = db.scalar(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id
        ).order_by(EvidenceRecord.seq.desc()))
        assert last is not None
    manifest = {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "stripe_event_id": event_id,
        "run_id": run_id,
        "source_sha": "a" * 40,
        "evidence_tip": last.record_hash,
        "artifact_sha256": "1" * 64,
        "recipient_sha256": "2" * 64,
        "expires_at": int(time.time()) + 600,
    }
    return manifest


def _approved(tmp_path, monkeypatch, manifest):
    igor, owner = _review_keys(tmp_path, monkeypatch)
    signatures = {
        "igor": _sign(tmp_path, igor[0], "igor", manifest),
        "owner": _sign(tmp_path, owner[0], "owner", manifest),
    }
    return signatures, igor[1], owner[1]


def _reserve(manifest, signatures, keys):
    return reserve_delivery(manifest, signatures,
                            igor_public_key=keys[0], owner_public_key=keys[1])


def _records(tenant):
    with SessionLocal() as db:
        return db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant).order_by(EvidenceRecord.seq)).all()


def test_distinct_signed_igor_and_human_reserve_exactly_one_delivery(
    tenant_id, tmp_path, monkeypatch,
):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    before = len(_records(tenant_id))
    outcome = _reserve(manifest, signatures, (igor_pub, owner_pub))
    assert outcome["status"] == "DELIVERY_RESERVED"
    assert outcome["delivery_sent"] is False
    assert outcome["session_id"] == manifest["session_id"]
    assert len(_records(tenant_id)) == before + 1
    assert _records(tenant_id)[-1].record_type == "execution.delivery_reserved"

    with SessionLocal() as db:
        claim = db.get(StripeCheckoutClaim, manifest["session_id"])
        event = db.scalar(select(StripeEvent).where(
            StripeEvent.event_id == manifest["stripe_event_id"]))
        assert claim.status == event.status == "DELIVERY_RESERVED"
        assert claim.result_json == event.result_json
    rows = _records(tenant_id)
    assert verify_chain([{
        "tenant_id": r.tenant_id, "seq": r.seq, "record_type": r.record_type,
        "prev_hash": r.prev_hash, "record_hash": r.record_hash,
        "payload_json": r.payload_json,
    } for r in rows]) == (True, "ok")

    repeated = _reserve(manifest, signatures, (igor_pub, owner_pub))
    assert repeated["status"] == "ALREADY_RESERVED"
    assert repeated["delivery_sent"] is False
    assert len(_records(tenant_id)) == before + 1


def test_paid_but_unexecuted_order_blocks_even_with_valid_signatures(
    tenant_id, tmp_path, monkeypatch,
):
    manifest = _make_order(tenant_id, monkeypatch)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    with pytest.raises(ValueError, match="order"):
        _reserve(manifest, signatures, (igor_pub, owner_pub))
    assert all(r.record_type != "execution.delivery_reserved" for r in _records(tenant_id))


def test_forged_or_cross_role_signature_blocks(tenant_id, tmp_path, monkeypatch):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    forged = dict(signatures)
    forged["owner"] = forged["igor"]
    with pytest.raises(ValueError, match="signature"):
        _reserve(manifest, forged, (igor_pub, owner_pub))
    assert all(r.record_type != "execution.delivery_reserved" for r in _records(tenant_id))


def test_untrusted_key_or_missing_pin_blocks(tenant_id, tmp_path, monkeypatch):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    monkeypatch.delenv("OLA_OWNER_PUBKEY_SHA256")
    with pytest.raises(ValueError, match="pin"):
        _reserve(manifest, signatures, (igor_pub, owner_pub))
    monkeypatch.setenv("OLA_OWNER_PUBKEY_SHA256", "f" * 64)
    with pytest.raises(ValueError, match="pin"):
        _reserve(manifest, signatures, (igor_pub, owner_pub))


def test_wrong_source_or_stale_evidence_tip_blocks(tenant_id, tmp_path, monkeypatch):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    monkeypatch.setenv("OLA_RELEASE_SOURCE_SHA", "b" * 40)
    with pytest.raises(ValueError, match="source"):
        _reserve(manifest, signatures, (igor_pub, owner_pub))
    monkeypatch.setenv("OLA_RELEASE_SOURCE_SHA", "a" * 40)
    append_evidence_atomic(tenant_id, "audit.unrelated", {"detail": "advance-tip"})
    with pytest.raises(ValueError, match="tip"):
        _reserve(manifest, signatures, (igor_pub, owner_pub))


def test_expired_receipt_or_tampered_recipient_blocks(tenant_id, tmp_path, monkeypatch):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    altered = dict(manifest, recipient_sha256="3" * 64)
    with pytest.raises(ValueError, match="signature"):
        _reserve(altered, signatures, (igor_pub, owner_pub))
    expired = dict(manifest, expires_at=int(time.time()) - 1)
    with pytest.raises(ValueError, match="expired"):
        _reserve(expired, signatures, (igor_pub, owner_pub))


def test_replay_with_changed_recipient_never_reserves_second_delivery(
    tenant_id, tmp_path, monkeypatch,
):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    assert _reserve(manifest, signatures, (igor_pub, owner_pub))["status"] == "DELIVERY_RESERVED"
    changed = dict(manifest, recipient_sha256="3" * 64)
    changed_signatures = {
        "igor": _sign(tmp_path, _review_private(tmp_path, "igor"), "igor", changed),
        "owner": _sign(tmp_path, _review_private(tmp_path, "owner"), "owner", changed),
    }
    with pytest.raises(ValueError, match="reserved|conflict"):
        _reserve(changed, changed_signatures, (igor_pub, owner_pub))
    assert sum(r.record_type == "execution.delivery_reserved" for r in _records(tenant_id)) == 1


def _review_private(tmp_path, role):
    return tmp_path / (role + "-private.pem")


def test_dry_run_validates_without_reserving(tenant_id, tmp_path, monkeypatch):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    before = len(_records(tenant_id))
    outcome = reserve_delivery(
        manifest, signatures, igor_public_key=igor_pub,
        owner_public_key=owner_pub, dry_run=True,
    )
    assert outcome["status"] == "READY_TO_RESERVE"
    assert outcome["delivery_sent"] is False
    assert len(_records(tenant_id)) == before
    with SessionLocal() as db:
        assert db.get(StripeCheckoutClaim, manifest["session_id"]).status == (
            "PENDING_INDEPENDENT_VERIFICATION"
        )


def test_operator_cli_dry_run_before_apply(tenant_id, tmp_path, monkeypatch):
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    signatures, igor_pub, owner_pub = _approved(tmp_path, monkeypatch, manifest)
    manifest_path = tmp_path / "manifest.json"
    signatures_path = tmp_path / "approvals.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    signatures_path.write_text(json.dumps(signatures), encoding="utf-8")
    command = [
        sys.executable, "-m", "scripts.reserve_signed_delivery",
        "--manifest", str(manifest_path), "--approvals", str(signatures_path),
        "--igor-public", str(igor_pub), "--owner-public", str(owner_pub),
    ]
    before = len(_records(tenant_id))
    probe = subprocess.run(command, capture_output=True, text=True,
                           env=dict(os.environ), timeout=25)
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout)["status"] == "READY_TO_RESERVE"
    assert len(_records(tenant_id)) == before

    applied = subprocess.run(command + ["--apply"], capture_output=True,
                             text=True, env=dict(os.environ), timeout=25)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["status"] == "DELIVERY_RESERVED"
    assert len(_records(tenant_id)) == before + 1
    assert _records(tenant_id)[-1].record_type == "execution.delivery_reserved"

    repeated = subprocess.run(command + ["--apply"], capture_output=True,
                              text=True, env=dict(os.environ), timeout=25)
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["status"] == "ALREADY_RESERVED"
    assert len(_records(tenant_id)) == before + 1
