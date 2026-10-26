"""Operator-only, fail-closed signed delivery reservation CLI.

READ-ONLY by default; the --apply flag writes one delivery reservation but
NEVER sends an artifact, grants customer access, or executes an agent.
"""
import argparse
import json
import sys
from pathlib import Path

from app.fulfillment_release import reserve_delivery


def _json_file(path: Path, maximum=32768):
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise ValueError("JSON input missing or oversized")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("JSON input must be an object")
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--approvals", required=True, type=Path)
    parser.add_argument("--igor-public", required=True, type=Path)
    parser.add_argument("--owner-public", required=True, type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="explicitly record a one-time reservation (no dispatch)")
    args = parser.parse_args()
    try:
        result = reserve_delivery(
            _json_file(args.manifest), _json_file(args.approvals),
            igor_public_key=args.igor_public, owner_public_key=args.owner_public,
            dry_run=not args.apply,
        )
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Do not print the contents of documents, signatures, key paths or PII.
        print("BLOCKED: %s" % type(exc).__name__, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
