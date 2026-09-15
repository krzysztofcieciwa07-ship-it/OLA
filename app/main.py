import hashlib
import json
import uuid
from fastapi import FastAPI, Header, HTTPException
from sqlalchemy import select
from .database import Base, engine, SessionLocal, install_append_only_triggers
from .models import Tenant, ApiKey, EvidenceRecord
from .hashchain import GENESIS_HASH, canonical_json, compute_record_hash, verify_chain
from .agent_runtime import run_agent_task
from .business_runtime import run_invoice_task

app = FastAPI(title="OLA Execution Gate")
Base.metadata.create_all(bind=engine)
install_append_only_triggers()


def tenant_from_key(raw_key):
    if not raw_key:
        raise HTTPException(status_code=401, detail="missing API key")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with SessionLocal() as db:
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
        if key is None:
            raise HTTPException(status_code=401, detail="invalid API key")
        return key.tenant_id


def append_record(tenant_id, record_type, payload):
    payload_json = canonical_json(payload)
    with SessionLocal() as db:
        last = db.scalar(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.desc())
        )
        seq = 0 if last is None else last.seq + 1
        prev_hash = GENESIS_HASH if last is None else last.record_hash
        record = EvidenceRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            seq=seq,
            record_type=record_type,
            payload_json=payload_json,
            prev_hash=prev_hash,
            record_hash=compute_record_hash(tenant_id, seq, prev_hash, payload_json),
        )
        db.add(record)
        db.commit()
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "seq": record.seq,
            "record_hash": record.record_hash,
        }


def run_controlled_audit(tenant_id, task, scenario):
    if scenario != "fault_then_recovery":
        raise HTTPException(status_code=400, detail="unsupported scenario")

    audit_id = str(uuid.uuid4())
    events = [
        ("task.received", {"audit_id": audit_id, "task": task}),
        ("execution.started", {"audit_id": audit_id, "mode": "controlled"}),
        ("fault.detected", {"audit_id": audit_id, "fault": "controlled_fault"}),
        ("recovery.applied", {"audit_id": audit_id, "action": "controlled_recovery"}),
        ("verification.passed", {"audit_id": audit_id, "assertion": "recovered_and_verified"}),
    ]
    evidence_ids = []
    for record_type, payload in events:
        evidence_ids.append(append_record(tenant_id, record_type, payload)["id"])

    with SessionLocal() as db:
        rows = db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.id.in_(evidence_ids),
            )
            .order_by(EvidenceRecord.seq.asc())
        ).all()

    chain = [
        {
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
            "payload_json": row.payload_json,
        }
        for row in rows
    ]
    chain_ok, reason = verify_chain(chain)
    if not chain_ok:
        return {
            "audit_id": audit_id,
            "status": "FAILED",
            "outcome": "evidence_chain_invalid",
            "evidence_count": len(rows),
            "evidence_ids": evidence_ids,
            "reason": reason,
        }

    return {
        "audit_id": audit_id,
        "status": "VERIFIED",
        "outcome": "recovered_and_verified",
        "evidence_count": len(rows),
        "evidence_ids": evidence_ids,
        "reason": reason,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/evidence")
def create_evidence(body: dict, x_api_key: str | None = Header(default=None)):
    tenant_id = tenant_from_key(x_api_key)
    return append_record(
        tenant_id,
        body.get("record_type", "generic"),
        body.get("payload", {}),
    )


@app.post("/audit")
def create_audit(body: dict, x_api_key: str | None = Header(default=None)):
    tenant_id = tenant_from_key(x_api_key)
    task = body.get("task")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")
    return run_controlled_audit(
        tenant_id,
        task,
        body.get("scenario", "fault_then_recovery"),
    )


@app.post("/agent-run")
def create_agent_run(body: dict, x_api_key: str | None = Header(default=None)):
    tenant_id = tenant_from_key(x_api_key)
    task = body.get("task")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")
    return run_agent_task(tenant_id, task)


@app.post("/business-invoice-run")
def create_business_invoice_run(body: dict, x_api_key: str | None = Header(default=None)):
    tenant_id = tenant_from_key(x_api_key)
    invoice = body.get("invoice")
    if not isinstance(invoice, dict):
        raise HTTPException(status_code=400, detail="invoice object is required")
    task = "INVOICE_JSON:" + canonical_json(invoice)
    try:
        return run_invoice_task(tenant_id, task)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/evidence/{record_id}")
def get_evidence(record_id: str, x_api_key: str | None = Header(default=None)):
    tenant_id = tenant_from_key(x_api_key)
    with SessionLocal() as db:
        record = db.scalar(
            select(EvidenceRecord).where(
                EvidenceRecord.id == record_id,
                EvidenceRecord.tenant_id == tenant_id,
            )
        )
        if record is None:
            raise HTTPException(status_code=404, detail="evidence not found")
        return {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "seq": record.seq,
            "record_type": record.record_type,
            "payload": json.loads(record.payload_json),
            "prev_hash": record.prev_hash,
            "record_hash": record.record_hash,
        }
