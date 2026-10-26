"""Fail-closed, tenant-scoped artifact staging after signed reservation."""
import hashlib
import json
import os
import uuid

import pytest
from sqlalchemy import select

from app.delivery_artifacts import stage_delivery
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.models import EvidenceRecord, StripeCheckoutClaim
from tests.test_signed_delivery_reservation import (
    _make_order, _approved, _reserve, _records, tenant_id,
)


def _setup(tenant_id, tmp_path, monkeypatch):
    root = tmp_path / "private-artifacts"
    root.mkdir()
    monkeypatch.setenv("OLA_DELIVERY_ARTIFACT_ROOT", str(root))
    file = root / "audit-report.pdf"
    file.write_bytes(b"%PDF-1.4\nOPAQUE PRIVATE REPORT TEST\n%%EOF")
    manifest = _make_order(tenant_id, monkeypatch, execution_proven=True)
    manifest["artifact_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    signatures, igor, owner = _approved(tmp_path, monkeypatch, manifest)
    reserved = _reserve(manifest, signatures, (igor, owner))
    assert reserved["status"] == "DELIVERY_RESERVED"
    return manifest, reserved["reservation_id"], file


def _stage(manifest, rid, *, filename="audit-report.pdf", dry_run=True,
           tenant_id_override=None, recipient_sha256=None):
    return stage_delivery(
        tenant_id_override or manifest["tenant_id"],
        manifest["session_id"], rid, filename,
        recipient_sha256 or manifest["recipient_sha256"], dry_run=dry_run,
    )


def _outbox_rows():
    with SessionLocal() as db:
        return db.connection().exec_driver_sql(
            "SELECT reservation_id, status, session_id, artifact_sha256 "
            "FROM delivery_artifact_outbox"
        ).all()


def test_dry_run_verifies_reserved_artifact_without_any_mutation(
    tenant_id, tmp_path, monkeypatch,
):
    manifest, rid, file = _setup(tenant_id, tmp_path, monkeypatch)
    before = len(_records(tenant_id))
    out = _stage(manifest, rid)
    assert out["status"] == "ARTIFACT_VALIDATED_NOT_STAGED"
    assert out["delivery_sent"] is False
    assert out["payment_rechecked"] is False
    assert len(_records(tenant_id)) == before
    assert _outbox_rows() == []


def test_apply_stages_one_artifact_but_cannot_send_or_approve_payment(
    tenant_id, tmp_path, monkeypatch,
):
    manifest, rid, file = _setup(tenant_id, tmp_path, monkeypatch)
    before = len(_records(tenant_id))
    result = _stage(manifest, rid, dry_run=False)
    assert result["status"] == "STAGED_AWAITING_PAYMENT_RECHECK"
    assert result["delivery_sent"] is False
    assert result["payment_rechecked"] is False
    assert len(_records(tenant_id)) == before + 1
    rows = _outbox_rows()
    assert len(rows) == 1
    assert tuple(rows[0]) == (
        rid, "STAGED_AWAITING_PAYMENT_RECHECK",
        manifest["session_id"], manifest["artifact_sha256"],
    )
    with SessionLocal() as db:
        assert db.get(StripeCheckoutClaim, manifest["session_id"]).status == "DELIVERY_RESERVED"
    chain = _records(tenant_id)
    assert chain[-1].record_type == "execution.artifact_staged"
    assert verify_chain([{
        "tenant_id": row.tenant_id, "seq": row.seq, "record_type": row.record_type,
        "prev_hash": row.prev_hash, "record_hash": row.record_hash,
        "payload_json": row.payload_json,
    } for row in chain]) == (True, "ok")

    again = _stage(manifest, rid, dry_run=False)
    assert again["status"] == "ALREADY_STAGED"
    assert again["delivery_sent"] is False
    assert len(_records(tenant_id)) == before + 1
    assert len(_outbox_rows()) == 1


def test_wrong_tenant_and_reservation_cannot_stage(tenant_id, tmp_path, monkeypatch):
    manifest, rid, _ = _setup(tenant_id, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="tenant|order|reservation"):
        _stage(manifest, rid, tenant_id_override=str(uuid.uuid4()), dry_run=False)
    with pytest.raises(ValueError, match="reservation"):
        _stage(manifest, str(uuid.uuid4()), dry_run=False)
    assert _outbox_rows() == []


def test_mismatched_file_digest_blocks_without_db_writes(tenant_id, tmp_path, monkeypatch):
    manifest, rid, file = _setup(tenant_id, tmp_path, monkeypatch)
    file.write_bytes(b"tampered payload")
    with pytest.raises(ValueError, match="artifact|digest"):
        _stage(manifest, rid, dry_run=False)
    assert _outbox_rows() == []


def test_path_traversal_or_symlink_blocks(tenant_id, tmp_path, monkeypatch):
    manifest, rid, file = _setup(tenant_id, tmp_path, monkeypatch)
    for name in ("../private.txt", "/tmp/private.txt", r"..\\private.txt",
                 "not-a-report.exe", ".hidden.pdf"):
        with pytest.raises(ValueError, match="filename|artifact|path"):
            _stage(manifest, rid, filename=name, dry_run=False)
    link = file.parent / "audit-linked.pdf"
    try:
        link.symlink_to(file)
    except (NotImplementedError, OSError):
        pytest.skip("host cannot create a test symlink")
    with pytest.raises(ValueError, match="symlink|artifact|path"):
        _stage(manifest, rid, filename=link.name, dry_run=False)
    assert _outbox_rows() == []


def test_missing_config_fails_closed(tenant_id, tmp_path, monkeypatch):
    manifest, rid, file = _setup(tenant_id, tmp_path, monkeypatch)
    monkeypatch.delenv("OLA_DELIVERY_ARTIFACT_ROOT")
    with pytest.raises(ValueError, match="root"):
        _stage(manifest, rid, dry_run=False)


def test_existing_stage_checks_chain_and_artifact_on_replay(
    tenant_id, tmp_path, monkeypatch,
):
    manifest, rid, file = _setup(tenant_id, tmp_path, monkeypatch)
    assert _stage(manifest, rid, dry_run=False)["status"] == "STAGED_AWAITING_PAYMENT_RECHECK"
    file.write_bytes(b"new conflicting content")
    with pytest.raises(ValueError, match="artifact|digest"):
        _stage(manifest, rid, dry_run=False)
    file.write_bytes(b"%PDF-1.4\nOPAQUE PRIVATE REPORT TEST\n%%EOF")
    with SessionLocal() as db:
        tip = db.scalar(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id
        ).order_by(EvidenceRecord.seq.desc()))
        db.add(EvidenceRecord(
            id=str(uuid.uuid4()), tenant_id=tenant_id, seq=tip.seq + 1,
            record_type="tamper.probe", payload_json="{}", prev_hash=tip.record_hash,
            record_hash="f" * 64,
        ))
        db.commit()
    with pytest.raises(ValueError, match="chain|Evidence"):
        _stage(manifest, rid, dry_run=False)
    assert len(_outbox_rows()) == 1
