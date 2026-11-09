#!/usr/bin/env python3
"""Create an ephemeral challenge and private assertion policy for one lab run."""
import argparse
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("scenarios/certificate-apocalypse/runtime"))
    args = parser.parse_args()
    runtime = args.output.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    # Docker Compose project names are deliberately lowercase.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%sz") + "-" + secrets.token_hex(5)
    challenge = secrets.token_urlsafe(32)
    fault_after = secrets.randbelow(7) + 7
    fault_duration = secrets.randbelow(6) + 9
    stability = secrets.randbelow(5) + 8
    total = fault_after + fault_duration + stability + 8
    context = {
        "schema": "ola-chaos-run-context/v0",
        "run_id": run_id,
        "challenge": challenge,
        "challenge_sha256": hashlib.sha256(challenge.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fault_after_seconds": fault_after,
        "fault_duration_seconds": fault_duration,
        "stability_seconds": stability,
        "max_probe_gap_seconds": 2.5,
        "probe_interval_seconds": 0.5,
        "load_duration_seconds": total,
        "vus": secrets.randbelow(3) + 3,
        "p95_limit_ms": 500.0,
        "p99_limit_ms": 1000.0,
        "policy_source": "runner_generated_private_policy"
    }
    (runtime / "run_context.json").write_text(
        json.dumps(context, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    cert_dir = runtime / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    env = {
        "OLA_SCENARIO_RUN_ID": run_id,
        "OLA_SCENARIO_CHALLENGE": challenge,
        "OLA_CERT_DIR": str(cert_dir),
        "OLA_COMPOSE_PROJECT": "ola-ca-" + run_id.replace("-", "")[:20],
        "OLA_UID": str(os.getuid() if hasattr(os, "getuid") else 1000),
        "OLA_GID": str(os.getgid() if hasattr(os, "getgid") else 1000),
        "TLS_PORT": "8443",
        "CONTROL_PORT": "8080"
    }
    (runtime / "scenario.env").write_text(
        "".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8"
    )
    for name in ("events.jsonl", "certificate-events.jsonl", "command-ledger.jsonl", "probe-samples.jsonl"):
        (runtime / name).write_text("", encoding="utf-8")
    print(json.dumps({
        "run_id": run_id,
        "challenge_sha256": context["challenge_sha256"],
        "fault_after_seconds": fault_after,
        "fault_duration_seconds": fault_duration,
        "stability_seconds": stability,
        "load_duration_seconds": total
    }, sort_keys=True))


if __name__ == "__main__":
    main()
