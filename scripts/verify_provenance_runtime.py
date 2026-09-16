import argparse
import json
import os
import subprocess
import sys


def block(reason):
    return {"status": "BLOCK", "reason": reason}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-task")
    parser.add_argument("--expected-result")
    parser.add_argument("--db-path", default=os.getenv("OLA_EG_DB_PATH", "/data/ola.db"))
    args = parser.parse_args()

    actual_commit = os.getenv("OLA_RUNTIME_COMMIT")
    if not actual_commit:
        result = block("runtime commit provenance is missing")
        print(json.dumps(result, sort_keys=True))
        return 1
    if actual_commit != args.expected_commit:
        result = block(
            "commit provenance mismatch",
            expected_commit=args.expected_commit,
            actual_commit=actual_commit,
        )
        print(json.dumps(result, sort_keys=True))
        return 1

    command = [
        "python", "scripts/verify_agent_runtime.py",
        "--tenant-id", args.tenant_id,
        "--run-id", args.run_id,
        "--expected-commit", actual_commit,
        "--db-path", args.db_path,
    ]
    if args.expected_task is not None:
        command += ["--expected-task", args.expected_task]
    if args.expected_result is not None:
        command += ["--expected-result", args.expected_result]

    verifier = subprocess.run(command, capture_output=True, text=True)
    stdout = verifier.stdout.strip()
    stderr = verifier.stderr.strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    return verifier.returncode


if __name__ == "__main__":
    raise SystemExit(main())
