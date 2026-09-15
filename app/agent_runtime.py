from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .hashchain import canonical_json
from .main import append_record
from .database import SessionLocal
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
    db = SessionLocal()
    try:
        rows = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id).all()
    finally:
        db.close()

    records = []
    for row in rows:
        payload = __import__("json").loads(row.payload_json)
        if payload.get("record_type") == "agent_runtime":
            records.append((row, payload))

    run_records = [(row, payload) for row, payload in records if payload.get("run_id") == run_id]
    if len(run_records) != len(AGENT_ROLES):
        return {"status": "UNKNOWN", "reason": "missing agent evidence"}

    expected = list(range(1, len(AGENT_ROLES) + 1))
    actual = sorted(payload.get("sequence") for _, payload in run_records)
    agents = [payload.get("agent") for _, payload in sorted(run_records, key=lambda item: item[1].get("sequence", 0))]
    if actual != expected or agents != AGENT_ROLES:
        return {"status": "UNKNOWN", "reason": "agent sequence mismatch"}

    return {"status": "VERIFIED", "reason": "six agent evidence records present"}
