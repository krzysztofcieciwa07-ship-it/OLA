import argparse
import json
import os
import sys

os.environ.setdefault("OLA_EG_DB_PATH", "/data/ola.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.agent_runtime import AGENT_ROLES
from app.database import SessionLocal
from app.hashchain import verify_chain
from app.models import EvidenceRecord

EXPECTED_CAPABILITIES = {
    "codeact": "executed_safe_expression",
    "react": "reason_act_observe",
    "agentic_rag": "retrieved_prior_evidence",
    "mcp_tool_use": "invoked_tool",
    "self_reflection": "checked_previous_output",
    "multi_agent": "aggregated_agent_outputs",
}


def verify(tenant_id, run_id, expected_commit):
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

    expected_types = [f"agent.{role}" for role in AGENT_ROLES]
    if [row.record_type for row in run_rows] != expected_types:
        return {"status": "BLOCK", "reason": "six-agent evidence missing or out of order"}

    capabilities = {}
    for row in run_rows:
        payload = json.loads(row.payload_json)
        agent = payload.get("agent")
        required = {"capability", "tool", "tool_output", "result", "status"}
        if not required.issubset(payload):
            return {"status": "BLOCK", "reason": f"execution evidence incomplete for {agent}"}
        if payload.get("status") != "VERIFIED":
            return {"status": "BLOCK", "reason": f"execution not verified for {agent}"}
        if payload.get("capability") != EXPECTED_CAPABILITIES.get(agent):
            return {"status": "BLOCK", "reason": f"unexpected capability for {agent}"}
        capabilities[agent] = payload["capability"]

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
        return {"status": "BLOCK", "reason": reason}

    return {
        "status": "VERIFIED",
        "run_id": run_id,
        "commit": expected_commit,
        "agents": AGENT_ROLES,
        "capabilities": capabilities,
        "evidence_count": len(run_rows),
        "reason": "independent verifier recomputed execution capabilities and complete evidence chain",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-commit", default=os.getenv("GITHUB_SHA", "UNKNOWN"))
    args = parser.parse_args()
    result = verify(args.tenant_id, args.run_id, args.expected_commit)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result["status"] == "VERIFIED" else 1)


if __name__ == "__main__":
    main()
