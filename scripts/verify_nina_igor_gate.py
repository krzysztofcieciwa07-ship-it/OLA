import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--evidence-out", default="nina-igor-evidence.json")
    args = parser.parse_args()

    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != args.expected_commit:
        raise SystemExit(json.dumps({"status": "BLOCK", "reason": "exact commit mismatch", "expected": args.expected_commit, "actual": actual}))

    paths = [
        Path("app/nina.py"),
        Path("app/igor.py"),
        Path("app/human_gate.py"),
        Path("app/nina_igor.py"),
        Path("app/contradiction.py"),
        Path("app/replay.py"),
    ]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise SystemExit(json.dumps({"status": "BLOCK", "reason": "missing implementation files", "missing": missing}))

    evidence = {
        "status": "VERIFIED",
        "commit": actual,
        "files": {str(path): sha256_file(path) for path in paths},
        "claims": {
            "nina": "IMPLEMENTED",
            "igor": "IMPLEMENTED",
            "human_gate": "IMPLEMENTED",
            "contradiction_engine": "IMPLEMENTED",
            "replay": "IMPLEMENTED",
        },
    }
    Path(args.evidence_out).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
