#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from traceforge.engine import TraceForgeEngine


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TRACEFORGE v0 proof: acquire -> verify -> replay -> recover"
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--query", default="TRACEFORGE v0 proof")
    parser.add_argument("--route", default="local_file")
    parser.add_argument("--exercise-recovery", action="store_true")
    args = parser.parse_args()

    engine = TraceForgeEngine(args.root)
    acquired = engine.acquire(
        query=args.query,
        source=args.source,
        route=args.route,
    )
    verified = engine.verify(acquired["artifact_id"])
    if verified["status"] != "VERIFIED":
        print(
            json.dumps(
                {"final_status": "BLOCKED", "stage": "verify", "result": verified},
                sort_keys=True,
            )
        )
        return 2

    first_replay = engine.replay()
    if first_replay["status"] != "VERIFIED":
        print(
            json.dumps(
                {"final_status": "BLOCKED", "stage": "replay", "result": first_replay},
                sort_keys=True,
            )
        )
        return 3

    recovery = None
    if args.exercise_recovery:
        Path(acquired["artifact_path"]).unlink()
        recovery = engine.recover(acquired["artifact_id"])
        if recovery["status"] != "VERIFIED":
            print(
                json.dumps(
                    {"final_status": "BLOCKED", "stage": "recovery", "result": recovery},
                    sort_keys=True,
                )
            )
            return 4

    final_replay = engine.replay()
    package = engine.export_package()
    out = {
        "final_status": (
            "VERIFIED" if final_replay["status"] == "VERIFIED" else "BLOCKED"
        ),
        "artifact_id": acquired["artifact_id"],
        "sha256": acquired["sha256"],
        "verify": verified,
        "recovery": recovery,
        "replay": final_replay,
        "manifest": package["manifest"],
        "manifest_path": package["manifest_path"],
    }
    print(json.dumps(out, sort_keys=True))
    return 0 if out["final_status"] == "VERIFIED" else 5


if __name__ == "__main__":
    raise SystemExit(main())
