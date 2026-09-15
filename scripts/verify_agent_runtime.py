from __future__ import annotations

import sys

from app.agent_runtime import verify_agent_run
from app.database import SessionLocal
from app.models import EvidenceRecord


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_agent_runtime.py TENANT_ID RUN_ID")
        return 2
    tenant_id, run_id = sys.argv[1:]
    result = verify_agent_run(tenant_id, run_id)
    print(result)
    return 0 if result.get("status") == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
