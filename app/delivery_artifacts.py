"""Fail-closed operator-only artifact staging for an existing signed reservation.

This module only validates and records immutable staging *intent*; it never
sends a file, grants customer access, asserts Stripe refund status or treats
an artifact as delivered. Human/IGOR proof is inherited from a reservation
already stored in the append-only tenant Evidence chain.
"""
import hashlib
import hmac
import json
import os
import re
import stat
import uuid
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .fulfillment_release import _chain_rows, _trusted_payload, ORDER_RESERVED, RECORD_TYPE
from .hashchain import compute_record_hash_v2, sealed_payload_json
from .models import (
    DeliveryArtifactOutbox, EvidenceRecord, StripeCheckoutClaim, StripeEvent,
)

STAGED = "STAGED_AWAITING_PAYMENT_RECHECK"
RECORD_STAGED = "execution.artifact_staged"
FILENAME = re.compile("^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
HEX64 = re.compile("^[0-9a-f]{64}$")
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


def _artifact_digest(filename):
    root_text = os.getenv("OLA_DELIVERY_ARTIFACT_ROOT", "")
    if not root_text:
        raise ValueError("trusted artifact root not configured")
    root = Path(root_text)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("trusted artifact root must be an existing non-symlink directory")
    if (not isinstance(filename, str)
            or not FILENAME.fullmatch(filename)
            or filename.startswith(".")
            or filename.lower().split(".")[-1] not in {"pdf", "zip", "json"}
            or filename != Path(filename).name
            or "/" in filename or "\\" in filename):
        raise ValueError("invalid artifact filename or path")
    path = root / filename
    if path.is_symlink():
        raise ValueError("artifact symlink is forbidden")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size < 1
                    or info.st_size > MAX_ARTIFACT_BYTES):
                raise ValueError("artifact missing or outside size limit")
            digest = hashlib.sha256()
            total = 0
            for data in iter(lambda: stream.read(65536), b""):
                total += len(data)
                if total > MAX_ARTIFACT_BYTES:
                    raise ValueError("artifact exceeded size limit")
                digest.update(data)
            if total != info.st_size:
                raise ValueError("artifact changed during digest calculation")
    except OSError as exc:
        raise ValueError("artifact cannot be opened safely") from exc
    return digest.hexdigest()


def _validated_reservation(db, tenant_id, session_id, reservation_id,
                           artifact_sha256, recipient_sha256, rows):
    claim = db.get(StripeCheckoutClaim, session_id)
    if claim is None or claim.tenant_id != tenant_id or claim.status != ORDER_RESERVED:
        raise ValueError("order tenant or reservation state invalid")
    event = db.scalar(select(StripeEvent).where(StripeEvent.event_id == claim.event_id))
    if (event is None or event.status != ORDER_RESERVED
            or event.result_json != claim.result_json or event.task != claim.task):
        raise ValueError("order event/reservation binding invalid")
    try:
        state = json.loads(claim.result_json)
        booking = state["delivery_reservation"]
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("reservation state unavailable") from exc
    if (state.get("status") != ORDER_RESERVED
            or booking.get("id") != reservation_id
            or booking.get("delivery_sent") is not False):
        raise ValueError("reservation mismatch or order already delivered")
    proofs = [row for row in rows if
              row.record_type == RECORD_TYPE
              and row.record_hash == booking.get("evidence_record_hash")]
    if len(proofs) != 1:
        raise ValueError("reservation Evidence proof missing")
    record = proofs[0]
    proof = _trusted_payload(record)
    if (proof.get("reservation_id") != reservation_id
            or proof.get("session_id") != session_id
            or proof.get("stripe_event_id") != claim.event_id
            or proof.get("artifact_sha256") != artifact_sha256
            or proof.get("recipient_sha256") != recipient_sha256
            or proof.get("delivery_sent") is not False):
        raise ValueError("reservation artifact or recipient digest mismatch")
    return record


def stage_delivery(tenant_id, session_id, reservation_id, filename,
                   recipient_sha256, *, dry_run=True):
    """Check and stage one artifact; no sending, entitlement or payment decision.

    Same immutable reservation may be staged once; retries re-verify the full
    Evidence chain AND the current file's hash, not only the database status.
    """
    if (not isinstance(tenant_id, str) or not isinstance(session_id, str)
            or not isinstance(reservation_id, str)
            or not isinstance(recipient_sha256, str)
            or not HEX64.fullmatch(recipient_sha256)):
        raise ValueError("tenant/recipient/reservation identifiers are invalid")
    artifact_sha256 = _artifact_digest(filename)

    with SessionLocal() as db:
        if db.bind.dialect.name != "sqlite":
            raise ValueError("atomic delivery staging backend is unavailable")
        if not dry_run:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        # Before reading tenant Evidence, ensure the authenticated operator
        # selected an order that actually belongs to this tenant.
        claim_owner = db.get(StripeCheckoutClaim, session_id)
        if claim_owner is None or claim_owner.tenant_id != tenant_id:
            raise ValueError("order tenant mismatch")
        rows = _chain_rows(db, tenant_id)
        record = _validated_reservation(
            db, tenant_id, session_id, reservation_id,
            artifact_sha256, recipient_sha256, rows,
        )
        existing = db.get(DeliveryArtifactOutbox, reservation_id)
        if existing is not None:
            if (existing.tenant_id != tenant_id
                    or existing.session_id != session_id
                    or existing.status != STAGED
                    or existing.artifact_sha256 != artifact_sha256
                    or existing.recipient_sha256 != recipient_sha256
                    or existing.artifact_filename != filename):
                raise ValueError("artifact already staged for different reservation")
            staged = [row for row in rows if
                      row.record_type == RECORD_STAGED
                      and row.record_hash == existing.evidence_hash]
            if len(staged) != 1:
                raise ValueError("staged artifact Evidence missing")
            body = _trusted_payload(staged[0])
            if (body.get("reservation_id") != reservation_id
                    or body.get("artifact_sha256") != artifact_sha256
                    or body.get("recipient_sha256") != recipient_sha256
                    or body.get("reservation_evidence_hash") != record.record_hash
                    or body.get("filename") != filename
                    or body.get("delivery_sent") is not False
                    or body.get("payment_rechecked") is not False):
                raise ValueError("staged artifact Evidence proof invalid")
            return {"status": "ALREADY_STAGED", "delivery_sent": False,
                    "payment_rechecked": False, "reservation_id": reservation_id}
        if dry_run:
            return {"status": "ARTIFACT_VALIDATED_NOT_STAGED",
                    "delivery_sent": False, "payment_rechecked": False,
                    "reservation_id": reservation_id}

        evidence_payload = {
            "reservation_id": reservation_id,
            "reservation_evidence_hash": record.record_hash,
            "session_id": session_id, "artifact_sha256": artifact_sha256,
            "recipient_sha256": recipient_sha256, "filename": filename,
            "payment_rechecked": False, "delivery_sent": False,
        }
        sealed = sealed_payload_json(RECORD_STAGED, evidence_payload, producer="ola_runtime")
        seq = rows[-1].seq + 1
        record_hash = compute_record_hash_v2(
            tenant_id, seq, rows[-1].record_hash,
            RECORD_STAGED, "ola_runtime", sealed,
        )
        db.add(EvidenceRecord(
            id=str(uuid.uuid4()), tenant_id=tenant_id, seq=seq,
            record_type=RECORD_STAGED, payload_json=sealed,
            prev_hash=rows[-1].record_hash, record_hash=record_hash,
        ))
        db.add(DeliveryArtifactOutbox(
            reservation_id=reservation_id, tenant_id=tenant_id,
            session_id=session_id, status=STAGED,
            artifact_filename=filename, artifact_sha256=artifact_sha256,
            recipient_sha256=recipient_sha256, evidence_hash=record_hash,
        ))
        db.commit()
        return {"status": STAGED, "delivery_sent": False,
                "payment_rechecked": False, "reservation_id": reservation_id,
                "artifact_sha256": artifact_sha256, "evidence_hash": record_hash}
