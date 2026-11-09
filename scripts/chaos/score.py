#!/usr/bin/env python3
"""Calculate a transparent score and Ed25519-sign a hash manifest of raw evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def redact_runtime_secrets(document):
    """Remove per-run bearer challenge from Docker inspect before publishing evidence."""
    containers = document if isinstance(document, list) else [document]
    for container in containers:
        if not isinstance(container, dict):
            continue
        config = container.get("Config")
        if not isinstance(config, dict):
            continue
        environment = config.get("Env")
        if not isinstance(environment, list):
            continue
        config["Env"] = [
            "OLA_SCENARIO_CHALLENGE=<redacted>"
            if isinstance(item, str) and item.startswith("OLA_SCENARIO_CHALLENGE=")
            else item
            for item in environment
        ]
    return containers if isinstance(document, list) else containers[0]


def calculate_score(metrics, scoring, assertions_passed, slo):
    weights = scoring["weights"]
    availability_min = float(slo["availability_min"])
    p95_limit = float(slo["p95_max_ms"])
    p99_limit = float(slo["p99_max_ms"])
    baseline = max(0.0, min(1.0, float(metrics.get("baseline_availability") or 0.0)))
    recovery = max(0.0, min(1.0, float(metrics.get("recovery_availability") or 0.0)))
    availability_component = min(1.0, min(baseline, recovery) / availability_min)
    p95, p99 = metrics.get("p95_ms"), metrics.get("p99_ms")
    if p95 is None or p99 is None:
        latency_component = 0.0
    else:
        p95_component = min(1.0, p95_limit / max(float(p95), 0.001))
        p99_component = min(1.0, p99_limit / max(float(p99), 0.001))
        latency_component = (p95_component + p99_component) / 2.0
    mttr = metrics.get("mttr_seconds")
    recovery_component = max(0.0, 1.0 - min(float(mttr), 120.0) / 120.0) if mttr is not None else 0.0
    collateral_ratio = 1.0 if metrics.get("collateral_sentinel_failed") else 0.0
    components = {
        "availability": availability_component,
        "latency": latency_component,
        "time_to_recover": recovery_component,
        "blast_radius": 1.0 - collateral_ratio
    }
    raw = sum(weights[key] * components[key] for key in weights)
    penalties = scoring["penalties"]
    restart_count = int(metrics.get("restart_count") or 0)
    penalty = min(1.0, restart_count * penalties["per_restart"])
    if mttr is not None and float(mttr) > 60:
        penalty = min(1.0, penalty + penalties["downtime_over_60_seconds"])
    score = max(0.0, min(1.0, raw - penalty))
    thresholds = scoring["thresholds"]
    tier = "ELITE" if score >= thresholds["elite"] else (
        "MERIT" if score >= thresholds["merit"] else (
            "PASS" if score >= thresholds["pass"] else "FAIL"
        )
    )
    status = "PASS" if assertions_passed and score >= thresholds["pass"] else "FAIL"
    return {
        "schema": "ola-chaos-score/v0",
        "score": round(score, 6),
        "raw_weighted_score": round(raw, 6),
        "penalty": round(penalty, 6),
        "tier": tier if status == "PASS" else "FAIL",
        "status": status,
        "components": {key: round(value, 6) for key, value in components.items()},
        "weights": weights,
        "thresholds": thresholds,
        "slo": slo,
        "raw_metrics": metrics
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path("scenarios/certificate-apocalypse/runtime"))
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/certificate-apocalypse/scenario.json"))
    parser.add_argument("--schema", type=Path, default=Path("schemas/chaos-scenario-v0.schema.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    output = args.output.resolve() if args.output else runtime / "report"
    output.mkdir(parents=True, exist_ok=True)
    scenario = load_json(args.scenario)
    assertions = load_json(runtime / "assertions.json")
    score = calculate_score(
        assertions.get("metrics", {}),
        scenario["scoring"],
        assertions.get("status") == "PASS",
        scenario["traffic"]["slo"]
    )
    score["run_id"] = assertions.get("run_id")
    score_path = output / "score.json"
    score_path.write_text(json.dumps(score, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    source_files = {
        "scenario.json": args.scenario,
        "chaos-scenario-v0.schema.json": args.schema,
        "assertions.json": runtime / "assertions.json",
        "probe-samples.jsonl": runtime / "probe-samples.jsonl",
        "k6-summary.json": runtime / "k6-summary.json",
        "k6.log": runtime / "k6.log",
        "docker-compose.log": runtime / "docker-compose.log",
        "docker-inspect.json": runtime / "docker-inspect.json",
        "docker-events.jsonl": runtime / "docker-events.jsonl",
        "certificate-events.jsonl": runtime / "certificate-events.jsonl",
        "events.jsonl": runtime / "events.jsonl",
        "command-ledger.jsonl": runtime / "command-ledger.jsonl",
        "ca.crt": runtime / "certs" / "ca.crt",
        "good-server.crt": runtime / "good-server.crt",
        "bad-server.crt": runtime / "bad-server.crt"
    }
    file_hashes = {}
    missing = []
    for name, source in source_files.items():
        if source.is_file():
            target = output / name
            if name == "docker-inspect.json":
                # Runtime copy is deliberately left untouched in the ignored local directory.
                sanitized = redact_runtime_secrets(load_json(source))
                target.write_text(json.dumps(sanitized, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            else:
                shutil.copy2(source, target)
            file_hashes[name] = sha256(target)
        else:
            missing.append(name)
    file_hashes["score.json"] = sha256(score_path)

    context = load_json(runtime / "run_context.json")
    inspected_images = []
    inspect_path = runtime / "docker-inspect.json"
    if inspect_path.is_file():
        containers = load_json(inspect_path)
        if isinstance(containers, dict):
            containers = [containers]
        for container in containers:
            inspected_images.append({
                "container_id": container.get("Id"),
                "image_id": container.get("Image"),
                "configured_image": container.get("Config", {}).get("Image"),
                "repo_digests": container.get("RepoDigests", [])
            })
    manifest = {
        "schema": "ola-chaos-evidence-manifest/v0",
        "scenario_id": scenario["metadata"]["id"],
        "scenario_version": scenario["metadata"]["version"],
        "run_id": context["run_id"],
        "challenge_sha256": context["challenge_sha256"],
        "run_context_sha256": sha256(runtime / "run_context.json"),
        "scenario_schema_sha256": sha256(args.schema),
        "source_commit": os.environ.get("GITHUB_SHA", "LOCAL_UNPINNED"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "docker_images": inspected_images,
        "missing_evidence_files": missing,
        "files": file_hashes
    }
    manifest_path = output / "evidence-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    supplied_key = os.environ.get("OLA_EVIDENCE_SIGNING_KEY")
    if supplied_key:
        private_key = Path(supplied_key).resolve()
        if not private_key.is_file():
            raise SystemExit("OLA_EVIDENCE_SIGNING_KEY does not point to a readable PEM file")
        signer_type = "external_pem_key"
    else:
        private_key = runtime / "evidence-signing-key.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)], check=True)
        os.chmod(private_key, 0o600)
        signer_type = "ephemeral_per_run_key"
    public_key = output / "evidence-manifest.pub"
    subprocess.run(["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)], check=True)
    signature = output / "evidence-manifest.sig"
    subprocess.run([
        "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key),
        "-in", str(manifest_path), "-out", str(signature)
    ], check=True)
    verified = subprocess.run([
        "openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_key),
        "-rawin", "-in", str(manifest_path), "-sigfile", str(signature)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if verified.returncode != 0:
        raise SystemExit("Ed25519 evidence manifest self-verification failed")
    public_hash = sha256(public_key)
    trusted_pin = os.environ.get("OLA_EVIDENCE_TRUSTED_SIGNER_SHA256", "").lower()
    trust_status = "PINNED_PUBLIC_KEY" if trusted_pin and trusted_pin == public_hash else (
        "EXTERNAL_KEY_NOT_PINNED" if supplied_key else "UNPINNED_SELF_SIGNED"
    )
    signature_metadata = {
        "algorithm": "Ed25519",
        "signer_type": signer_type,
        "public_key_sha256": public_hash,
        "signature_sha256": sha256(signature),
        "self_verification": "PASS",
        "trust_status": trust_status,
        "note": "A self-contained key verifies integrity only; authenticity requires an independently pinned public key."
    }
    (output / "signature-metadata.json").write_text(
        json.dumps(signature_metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "run_id": context["run_id"],
        "score": score["score"],
        "tier": score["tier"],
        "status": score["status"],
        "signature": "PASS",
        "trust_status": trust_status,
        "report": str(output)
    }, sort_keys=True))
    if score["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
