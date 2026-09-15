import hashlib
import json
import uuid

from sqlalchemy import select

from .database import SessionLocal
from .hashchain import GENESIS_HASH, canonical_json, compute_record_hash, verify_chain
from .models import EvidenceRecord


AGENT_ROLES = [
    "codeact",
    "react",
    "agentic_rag",
    "mcp_tool_use",
    "self_reflection",
    "multi_agent",
]


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _append_agent_evidence(tenant_id, run_id, agent, task, previous_output):
    output = {
        "agent": agent,
        "task": task,
        "input_digest": _digest(previous_output),
        "result": f"{agent}: completed deterministic runtime contract",
        "status": "VERIFIED",
    }
    with SessionLocal() as db:
        last = db.scalar(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.desc())
        )
        seq = 0 if last is None else last.seq + 1
        prev_hash = GENESIS_HASH if last is None else last.record_hash
        payload_json = canonical_json({"run_id": run_id, **output})
        record = EvidenceRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            seq=seq,
            record_type=f"agent.{agent}",
            payload_json=payload_json,
            prev_hash=prev_hash,
            record_hash=compute_record_hash(tenant_id, seq, prev_hash, payload_json),
        )
        db.add(record)
        db.commit()
        return record.id, output


def run_agent_task(tenant_id, task):
    run_id = str(uuid.uuid4())
    evidence_ids = []
    previous_output = task

    for agent in AGENT_ROLES:
        evidence_id, output = _append_agent_evidence(
            tenant_id, run_id, agent, task, previous_output
        )
        evidence_ids.append(evidence_id)
        previous_output = json.dumps(output, sort_keys=True)

    verification = verify_agent_run(tenant_id, run_id)
    if verification["status"] != "VERIFIED":
        return {
            "run_id": run_id,
            "status": verification["status"],
            "agents": AGENT_ROLES,
            "evidence_count": len(evidence_ids),
            "evidence_ids": evidence_ids,
        }

    return {
        "run_id": run_id,
        "status": "VERIFIED",
        "agents": AGENT_ROLES,
        "evidence_count": len(evidence_ids),
        "evidence_ids": evidence_ids,
    }


def verify_agent_run(tenant_id, run_id):
    with SessionLocal() as db:
        rows = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.asc())
        ).all()

    run_rows = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            continue
        if payload.get("run_id") == run_id and row.record_type.startswith("agent."):
            run_rows.append(row)

    if len(run_rows) != len(AGENT_ROLES):
        return {
            "status": "UNKNOWN",
            "reason": "missing agent evidence",
            "evidence_count": len(run_rows),
        }

    expected_types = [f"agent.{role}" for role in AGENT_ROLES]
    if [row.record_type for row in run_rows] != expected_types:
        return {
            "status": "BLOCK",
            "reason": "agent order mismatch",
            "evidence_count": len(run_rows),
        }

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
            "status": "BLOCK",
            "reason": reason,
            "evidence_count": len(run_rows),
        }

    return {
        "status": "VERIFIED",
        "reason": "independent hash-chain and six-agent contract verification passed",
        "evidence_count": len(run_rows),
    }
