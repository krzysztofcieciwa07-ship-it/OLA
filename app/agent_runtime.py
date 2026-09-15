from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .database import SessionLocal
from .hashchain import canonical_json, verify_chain
from .main import append_record
from .models import EvidenceRecord

AGENT_ROLES = [
    "CodeAct",
    "ReAct",
    "Agentic RAG",
    "MCP/tool use",
    "self-reflection",
    "multi-agent orchestration",
]


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def run_agent_task(tenant_id: str, task: str) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    evidence_ids: list[str] = []

    for sequence, role in enumerate(AGENT_ROLES, start=1):
        output = {
            "run_id": run_id,
            "agent": role,
            "sequence": sequence,
            "task": task,
            "result": "completed",
        }
        record = append_record(
            tenant_id,
            "agent_runtime",
            {
                "run_id": run_id,
                "agent": role,
                "sequence": sequence,
                "input_digest": _digest(task),
                "output_digest": _digest(output),
                "action": "deterministic_local_contract",
                "result": "completed",
                "status": "VERIFIED",
            },
        )
        evidence_ids.append(record["id"])

    verification = verify_agent_run(tenant_id, run_id)
    return {
        "run_id": run_id,
        "status": verification["status"],
        "agents": AGENT_ROLES,
        "evidence_count": len(evidence_ids),
        "evidence_ids": evidence_ids,
    }


def verify_agent_run(tenant_id: str, run_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        rows = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id).all()

    run_rows = []
    for row in rows:
        if row.record_type != "agent_runtime":
            continue
        payload = json.loads(row.payload_json)
        if payload.get("run_id") == run_id:
            run_rows.append(row)

    if len(run_rows) != len(AGENT_ROLES):
        return {"status": "UNKNOWN", "reason": "missing agent evidence"}

    run_rows.sort(key=lambda row: row.seq)
    payloads = [json.loads(row.payload_json) for row in run_rows]
    if [p.get("sequence") for p in payloads] != list(range(1, len(AGENT_ROLES) + 1)):
        return {"status": "UNKNOWN", "reason": "agent sequence mismatch"}
    if [p.get("agent") for p in payloads] != AGENT_ROLES:
        return {"status": "UNKNOWN", "reason": "agent role mismatch"}

    chain = [
        {
            "tenant_id": row.tenant_id,
            "seq": row.seq,
            "prev_hash": row.prev_hash,
            "record_hash": row.record_hash,
            "payload_json": row.payload_json,
        }
        for row in run_rows
    ]
    chain_ok, reason = verify_chain(chain)
    if not chain_ok:
        return {"status": "UNKNOWN", "reason": reason}

    return {"status": "VERIFIED", "reason": "six agent evidence records and chain verified"}
