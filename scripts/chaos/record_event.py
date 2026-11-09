#!/usr/bin/env python3
"""Append timestamped runner events bound to the private per-run challenge."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("event")
    parser.add_argument("--runtime", type=Path, default=Path("scenarios/certificate-apocalypse/runtime"))
    parser.add_argument("--detail", default="")
    args = parser.parse_args()
    context = json.loads((args.runtime / "run_context.json").read_text(encoding="utf-8"))
    item = {
        "event": args.event,
        "timestamp_epoch": time.time(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": context["run_id"],
        "challenge_sha256": hashlib.sha256(context["challenge"].encode()).hexdigest(),
        "detail": args.detail
    }
    with (args.runtime / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, sort_keys=True) + "\n")
    with (args.runtime / "command-ledger.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "timestamp_epoch": item["timestamp_epoch"],
            "run_id": item["run_id"],
            "argv": sys.argv[1:],
            "operation": args.event,
            "detail": args.detail
        }, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
