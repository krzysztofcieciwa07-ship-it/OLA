#!/usr/bin/env python3
"""Create an ephemeral challenge and run-specific policy from the scenario DSL."""
import argparse
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("scenarios/certificate-apocalypse/runtime"))
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/certificate-apocalypse/scenario.json"))
    args = parser.parse_args()
    runtime = args.output.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    target_url = urlsplit(scenario["target"]["base_url"])
    if target_url.scheme != "https" or target_url.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("chaos target must be an HTTPS loopback URL")
    target_host = target_url.hostname
    target_port = target_url.port or 443
    target_base_url = scenario["target"]["base_url"].rstrip("/") + "/health"
    # Docker Compose project names are deliberately lowercase.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%sz") + "-" + secrets.token_hex(5)
    challenge = secrets.token_urlsafe(32)
    fault_policy = scenario["anti_llm"]["randomized_fault_window"]
    fault_after = secrets.randbelow(
        fault_policy["max_seconds"] - fault_policy["min_seconds"] + 1
    ) + fault_policy["min_seconds"]
    fault_duration = scenario["fault"]["schedule"]["fault_duration_seconds"]
    stability_min = scenario["anti_llm"]["min_stable_seconds"]
    stability = stability_min + secrets.randbelow(5)
    base_vus = scenario["traffic"]["vus"]
    vus = max(1, base_vus + secrets.choice((-1, 0, 1)))
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
        "max_probe_gap_seconds": scenario["anti_llm"]["max_probe_gap_seconds"],
        "probe_interval_seconds": 0.5,
        "load_duration_seconds": total,
        "vus": vus,
        "request_timeout": scenario["traffic"]["request_timeout"],
        "base_url": target_base_url,
        "target_host": target_host,
        "target_port": target_port,
        "slo": scenario["traffic"]["slo"],
        "policy_source": "scenario_dsl_plus_runner_randomization"
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
        "OLA_TLS_HOST": target_host,
        "TLS_PORT": str(target_port),
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
        "vus": vus,
        "request_timeout": context["request_timeout"],
        "load_duration_seconds": total
    }, sort_keys=True))


if __name__ == "__main__":
    main()
