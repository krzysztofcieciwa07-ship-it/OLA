"""Fail-closed, operator-only reservation for independently signed order delivery.

A reserved artifact is NEVER SENT by this code. Review identities are
separately pinned Ed25519 public keys managed outside the customer API.
Any real delivery needs a separate, audited channel/receipt implementation.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from .agent_runtime import AGENT_ROLES, verify_agent_run
from .database import SessionLocal
from .hashchain import (
    EVIDENCE_META_KEY, GENESIS_HASH, canonical_json,
    compute_record_hash_v2, sealed_payload_json, verify_chain,
)
from .models import EvidenceRecord, StripeCheckoutClaim, StripeEvent
from .stripe_webhook import OLA_OFFER, OLA_PRODUCT


DOMAIN = "OLA-ORDER-DELIVERY-RELEASE-V1"
RECORD_TYPE = "execution.delivery_reserved"
ORDER_READY = "PENDING_INDEPENDENT_VERIFICATION"
ORDER_RESERVED = "DELIVERY_RESERVED"
FIELDS = frozenset({
    "tenant_id", "session_id", "stripe_event_id", "run_id", "source_sha",
    "evidence_tip", "artifact_sha256", "recipient_sha256", "expires_at",
})
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_PUBKEY_BYTES = 8192


def _hex64(value):
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or frozenset(manifest) != FIELDS:
        raise ValueError("manifest must contain exact delivery binding")
    for name in ("artifact_sha256", "recipient_sha256", "evidence_tip"):
        if not _hex64(manifest[name]):
            raise ValueError("invalid manifest digest")
    if not isinstance(manifest["source_sha"], str) or not HEX40.fullmatch(manifest["source_sha"]):
        raise ValueError("invalid source SHA")
    expected_source = os.getenv("OLA_RELEASE_SOURCE_SHA", "")
    if not HEX40.fullmatch(expected_source) or manifest["source_sha"] != expected_source:
        raise ValueError("source SHA is not bound to this authorized operator runtime")
    if (not isinstance(manifest["tenant_id"], str)
            or not isinstance(manifest["session_id"], str)
            or not isinstance(manifest["stripe_event_id"], str)
            or not isinstance(manifest["run_id"], str)
            or len(manifest["tenant_id"]) != 36
            or not manifest["session_id"].startswith("cs_")
            or not manifest["stripe_event_id"].startswith("evt_")
            or not manifest["run_id"]):
        raise ValueError("invalid order identity")
    expiry = manifest["expires_at"]
    now = int(time.time())
    if type(expiry) is not int or expiry <= now or expiry > now + 3600:
        raise ValueError("manifest expired or unbounded")


def _trusted_public_key(path, expected_pin):
    if not _hex64(expected_pin):
        raise ValueError("trusted grader/owner public-key pin missing or malformed")
    try:
        with Path(path).open("rb") as stream:
            pem = stream.read(MAX_PUBKEY_BYTES + 1)
    except OSError as exc:
        raise ValueError("trusted public-key path unavailable") from exc
    if not pem or len(pem) > MAX_PUBKEY_BYTES or b"-----BEGIN PUBLIC KEY-----" not in pem:
        raise ValueError("public-key PEM missing or oversized")
    digest = hashlib.sha256(pem).hexdigest()
    if not hmac.compare_digest(digest, expected_pin):
        raise ValueError("public-key pin mismatch")
    return pem, digest


def _check_signature(role, manifest, encoded, public_pem):
    if not isinstance(encoded, str) or len(encoded) > 512:
        raise ValueError("invalid signed approval signature")
    try:
        sig = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid signed approval signature encoding") from exc
    if len(sig) != 64:
        raise ValueError("invalid Ed25519 signature size")
    raw = canonical_json({"domain": DOMAIN, "role": role, "manifest": manifest}).encode("utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="ola_delivery_verify_") as directory:
            folder = Path(directory)
            pub = folder / "key.pem"
            msg = folder / "message.bin"
            signature = folder / "sig.bin"
            pub.write_bytes(public_pem)
            msg.write_bytes(raw)
            signature.write_bytes(sig)
            key_type = subprocess.run(
                ["openssl", "pkey", "-pubin", "-in", str(pub), "-text", "-noout"],
                capture_output=True, timeout=10, check=False,
            )
            if key_type.returncode != 0 or b"ED25519" not in key_type.stdout.upper():
                raise ValueError("trusted key is not an Ed25519 public key")
            result = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pub),
                 "-rawin", "-in", str(msg), "-sigfile", str(signature)],
                capture_output=True, timeout=10, check=False,
            )
            if result.returncode != 0:
                raise ValueError("signed approval signature invalid")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        raise ValueError("signature verification unavailable") from exc


def _attested(manifest, signatures, igor_public_key, owner_public_key):
    if not isinstance(signatures, dict) or set(signatures) != {"igor", "owner"}:
        raise ValueError("two independently signed approvals required")
    igor_pem, igor_pin = _trusted_public_key(
        igor_public_key, os.getenv("OLA_IGOR_PUBKEY_SHA256", "")
    )
    owner_pem, owner_pin = _trusted_public_key(
        owner_public_key, os.getenv("OLA_OWNER_PUBKEY_SHA256", "")
    )
    if hmac.compare_digest(igor_pin, owner_pin):
        raise ValueError("independent signer pins must differ")
    _check_signature("igor", manifest, signatures["igor"], igor_pem)
    _check_signature("owner", manifest, signatures["owner"], owner_pem)
    return {"igor": igor_pin, "owner": owner_pin}


def _chain_rows(db, tenant_id):
    rows = db.scalars(select(EvidenceRecord).where(
        EvidenceRecord.tenant_id == tenant_id,
    ).order_by(EvidenceRecord.seq)).all()
    chain_ok, reason = verify_chain([{
        "tenant_id": r.tenant_id, "seq": r.seq,
        "prev_hash": r.prev_hash, "record_hash": r.record_hash,
        "record_type": r.record_type, "payload_json": r.payload_json,
    } for r in rows])
    if not rows or not chain_ok:
        raise ValueError("full Evidence chain is missing or invalid")
    return rows


def _trusted_payload(row):
    data = json.loads(row.payload_json)
    if data.get(EVIDENCE_META_KEY) != {
        "version": 2, "record_type": row.record_type, "producer": "ola_runtime",
    }:
        raise ValueError("untrusted evidence producer")
    return data


def _require_order_and_proof(db, manifest, rows):
    session_id = manifest["session_id"]
    tenant_id = manifest["tenant_id"]
    claim = db.get(StripeCheckoutClaim, session_id)
    if claim is None or claim.tenant_id != tenant_id or claim.event_id != manifest["stripe_event_id"]:
        raise ValueError("order tenant/event binding missing")
    event = db.scalar(select(StripeEvent).where(
        StripeEvent.event_id == manifest["stripe_event_id"],
    ))
    if event is None or event.status != claim.status or event.task != claim.task:
        raise ValueError("order event/state mismatch")
    return claim, event


def reserve_delivery(manifest, signatures, *, igor_public_key, owner_public_key):
    """Reserve one exact delivery intent after independent signature/proof checks.

    No execution, entitlement grant, email, URL creation or customer dispatch.
    Raises ValueError for missing/invalid evidence, expired approval, conflict.
    """
    _validate_manifest(manifest)
    pins = _attested(manifest, signatures, igor_public_key, owner_public_key)
    digest = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()

    with SessionLocal() as db:
        if db.bind.dialect.name != "sqlite":
            raise ValueError("atomic order reservation backend unavailable")
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        claim, event = _require_order_and_proof(db, manifest, None)

        if claim.status == ORDER_RESERVED:
            try:
                current = json.loads(claim.result_json)
                reservation = current["delivery_reservation"]
            except (TypeError, KeyError, ValueError) as exc:
                raise ValueError("reserved order has invalid persisted receipt") from exc
            if (current.get("status") == ORDER_RESERVED
                    and reservation.get("manifest_sha256") == digest
                    and reservation.get("delivery_sent") is False
                    and event.result_json == claim.result_json):
                return {"status": "ALREADY_RESERVED", "session_id": manifest["session_id"],
                        "delivery_sent": False, "reservation_id": reservation["id"]}
            raise ValueError("reserved order conflict; no second delivery possible")
        if claim.status != ORDER_READY or not claim.result_json:
            raise ValueError("order is not independently verified for release")

        try:
            state = json.loads(claim.result_json)
        except (ValueError, TypeError) as exc:
            raise ValueError("order persisted status is malformed") from exc
        if (state.get("status") != ORDER_READY
                or state.get("payment") != "CONFIRMED"
                or state.get("checkout_session_id") != manifest["session_id"]
                or state.get("event_id") != manifest["stripe_event_id"]
                or state.get("ola_run_id") != manifest["run_id"]
                or event.result_json != claim.result_json
                or event.run_id != manifest["run_id"]):
            raise ValueError("order result/run identity binding invalid")

        rows = _chain_rows(db, manifest["tenant_id"])
        if not hmac.compare_digest(rows[-1].record_hash, manifest["evidence_tip"]):
            raise ValueError("Evidence tip is stale")
        parsed = [(row, json.loads(row.payload_json)) for row in rows]
        payments = [(row, body) for row, body in parsed if
                    row.record_type == "stripe.payment_confirmed"
                    and body.get("checkout_session_id") == manifest["session_id"]
                    and body.get("stripe_event_id") == manifest["stripe_event_id"]]
        completions = [(row, body) for row, body in parsed if
                       row.record_type == "stripe.ola_execution_recorded"
                       and body.get("checkout_session_id") == manifest["session_id"]
                       and body.get("stripe_event_id") == manifest["stripe_event_id"]]
        if len(payments) != 1 or len(completions) != 1:
            raise ValueError("order payment/execution evidence is missing or ambiguous")
        payment_row, payment = payments[0]
        completion_row, completion = completions[0]
        _trusted_payload(payment_row)
        _trusted_payload(completion_row)
        if (payment.get("offer") != OLA_OFFER
                or payment.get("product") != OLA_PRODUCT
                or payment.get("currency") != "eur"
                or payment.get("amount_total") != 9900
                or payment.get("task") != claim.task
                or completion.get("ola_run_id") != manifest["run_id"]
                or completion.get("ola_status") != "VERIFIED"
                or completion.get("payment_evidence_id") != payment_row.id
                or completion.get("delivery_status") != ORDER_READY
                or not payment_row.seq < completion_row.seq):
            raise ValueError("order payment and verified run are not bound")
        agent_rows = [(row, body) for row, body in parsed if
                      row.record_type.startswith("agent.")
                      and body.get("run_id") == manifest["run_id"]]
        if (len(agent_rows) != len(AGENT_ROLES) or
                any(not payment_row.seq < row.seq < completion_row.seq
                    or body.get("task") != claim.task for row, body in agent_rows)):
            raise ValueError("agent execution evidence is not session-bound")
        if verify_agent_run(manifest["tenant_id"], manifest["run_id"]).get("status") != "VERIFIED":
            raise ValueError("IGOR runtime evidence verification did not pass")

        reservation_id = str(uuid.uuid4())
        payload = {
            "session_id": manifest["session_id"],
            "stripe_event_id": manifest["stripe_event_id"],
            "run_id": manifest["run_id"],
            "source_sha": manifest["source_sha"],
            "payment_evidence_id": payment_row.id,
            "execution_evidence_id": completion_row.id,
            "approved_tip": manifest["evidence_tip"],
            "artifact_sha256": manifest["artifact_sha256"],
            "recipient_sha256": manifest["recipient_sha256"],
            "approval_manifest_sha256": digest,
            "igor_key_sha256": pins["igor"], "owner_key_sha256": pins["owner"],
            "reservation_id": reservation_id,
            "delivery_sent": False,
        }
        sealed = sealed_payload_json(RECORD_TYPE, payload, producer="ola_runtime")
        last = rows[-1]
        seq = last.seq + 1
        record_hash = compute_record_hash_v2(
            manifest["tenant_id"], seq, last.record_hash,
            RECORD_TYPE, "ola_runtime", sealed,
        )
        db.add(EvidenceRecord(
            id=str(uuid.uuid4()), tenant_id=manifest["tenant_id"], seq=seq,
            record_type=RECORD_TYPE, payload_json=sealed,
            prev_hash=last.record_hash, record_hash=record_hash,
        ))
        state["status"] = ORDER_RESERVED
        state["delivery_reservation"] = {
            "id": reservation_id, "manifest_sha256": digest, "delivery_sent": False,
            "evidence_record_hash": record_hash,
        }
        claim.status = event.status = ORDER_RESERVED
        claim.result_json = event.result_json = canonical_json(state)
        db.commit()
        return {"status": ORDER_RESERVED, "session_id": manifest["session_id"],
                "delivery_sent": False, "reservation_id": reservation_id,
                "evidence_record_hash": record_hash}
