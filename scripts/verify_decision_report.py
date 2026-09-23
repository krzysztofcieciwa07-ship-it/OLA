#!/usr/bin/env python3
"""Independent verifier for an OLA decision report artifact."""
import argparse
import hashlib
import json
import sys

from app.hashchain import canonical_json


def verify(path: str) -> bool:
    with open(path, encoding="utf-8") as handle:
        report = json.load(handle)
    claimed = report.get("report_sha256")
    if not claimed:
        return False
    body = dict(report)
    body.pop("report_sha256", None)
    actual = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return actual == claimed and report.get("schema") == "ola.decision-report.v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    args = parser.parse_args()
    if not verify(args.report):
        print("DECISION_REPORT=BLOCK")
        return 1
    print("DECISION_REPORT=VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
