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
    instance_ids = set()
    context_digests = set()
    invocations = {}
    for row in run_rows:
        payload = json.loads(row.payload_json)
        agent = payload.get("agent")
        required = {
            "capability", "tool", "tool_output", "result", "status",
            "agent_instance_id", "execution_boundary", "context_digest",
            "invocation_type", "model", "provider",
        }
        if not required.issubset(payload):
            return {"status": "BLOCK", "reason": f"execution evidence incomplete for {agent}"}
        if payload.get("status") != "VERIFIED":
            return {"status": "BLOCK", "reason": f"execution not verified for {agent}"}
        if payload.get("capability") != EXPECTED_CAPABILITIES.get(agent):
            return {"status": "BLOCK", "reason": f"unexpected capability for {agent}"}
        if payload.get("execution_boundary") != "independent":
            return {"status": "BLOCK", "reason": f"non-independent execution boundary for {agent}"}
        instance_ids.add(payload["agent_instance_id"])
        context_digests.add(payload["context_digest"])
        invocations[agent] = {
            "provider": payload["provider"],
            "model": payload["model"],
            "invocation_type": payload["invocation_type"],
        }
        capabilities[agent] = payload["capability"]

    if len(instance_ids) != len(AGENT_ROLES):
        return {"status": "BLOCK", "reason": "agent instance identities are not unique"}
    if len(context_digests) != len(AGENT_ROLES):
        return {"status": "BLOCK", "reason": "agent contexts are not unique"}

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
        "independent_instance_count": len(instance_ids),
        "independent_context_count": len(context_digests),
        "invocations": invocations,
        "evidence_count": len(run_rows),
        "reason": "independent agent identities, contexts, execution capabilities and complete evidence chain recomputed independently",
    }


def _emit_runtime_diagnostic(result):
    message = json.dumps(result, sort_keys=True)
    print(message)
    try:
        with open("/proc/1/fd/1", "w", encoding="utf-8") as stream:
            stream.write(f"AGENT_VERIFIER_RESULT={message}\n")
            stream.flush()
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-commit", default=os.getenv("GITHUB_SHA", "UNKNOWN"))
    args = parser.parse_args()
    result = verify(args.tenant_id, args.run_id, args.expected_commit)
    _emit_runtime_diagnostic(result)
    sys.exit(0 if result["status"] == "VERIFIED" else 1)


if __name__ == "__main__":
    main()
