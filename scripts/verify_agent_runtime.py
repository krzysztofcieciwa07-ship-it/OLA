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
        "evidence_count": len(run_rows),
        "reason": "independent verifier recomputed the complete evidence chain",
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
