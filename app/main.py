import hashlib
import json
import uuid
from fastapi import FastAPI, Header, HTTPException
from sqlalchemy import select
from .database import Base, engine, SessionLocal, install_append_only_triggers
from .models import Tenant, ApiKey, EvidenceRecord
from .hashchain import GENESIS_HASH, canonical_json, compute_record_hash

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
