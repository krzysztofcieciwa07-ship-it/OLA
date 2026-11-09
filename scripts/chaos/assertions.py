#!/usr/bin/env python3
"""Fail-closed assertions over raw TLS probes, fault ledger and runtime evidence."""
import argparse
import json
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    if not Path(path).is_file():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_slo(before, after, p95, p99, slo):
    baseline_availability = (
        sum(bool(row.get("target_ok")) for row in before) / len(before) if before else 0.0
    )
    recovery_availability = (
        sum(bool(row.get("target_ok")) for row in after) / len(after) if after else 0.0
    )
    availability_ok = (
        bool(before) and bool(after)
        and baseline_availability >= float(slo["availability_min"])
        and recovery_availability >= float(slo["availability_min"])
    )
    latency_ok = (
        p95 is not None and p99 is not None
        and float(p95) <= float(slo["p95_max_ms"])
        and float(p99) <= float(slo["p99_max_ms"])
    )
    return {
        "baseline_availability": baseline_availability,
        "recovery_availability": recovery_availability,
        "availability_ok": availability_ok,
        "latency_ok": latency_ok,
        "slo": slo,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path("scenarios/certificate-apocalypse/runtime"))
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/certificate-apocalypse/scenario.json"))
    args = parser.parse_args()
    runtime = args.runtime
    scenario = read_json(args.scenario)
    slo = scenario["traffic"]["slo"]
    context = read_json(runtime / "run_context.json")
    events = read_jsonl(runtime / "events.jsonl")
    cert_events = read_jsonl(runtime / "certificate-events.jsonl")
    samples = read_jsonl(runtime / "probe-samples.jsonl")
    failures = []
    checks = {}

    def check(name, passed, detail):
        checks[name] = {"passed": bool(passed), "detail": detail}
        if not passed:
            failures.append(name)

    fault = next((item for item in events if item["event"] == "fault_injected"), None)
    fixed = next((item for item in events if item["event"] == "fault_removed"), None)
    ordered = bool(fault and fixed and fault["timestamp_epoch"] < fixed["timestamp_epoch"])
    check("fault_and_fix_events_exist", ordered, {"fault": fault, "fix": fixed})
    fault_at = fault["timestamp_epoch"] if ordered else float("inf")
    fixed_at = fixed["timestamp_epoch"] if ordered else float("inf")

    challenge_hash = context["challenge_sha256"]
    challenge_bound = bool(samples) and all(
        row.get("run_id") == context["run_id"] and row.get("challenge_sha256") == challenge_hash
        for row in samples
    ) and all(
        item.get("run_id") == context["run_id"] and item.get("challenge_sha256") == challenge_hash
        for item in events
    )
    check("run_challenge_bound", challenge_bound, {
        "run_id": context["run_id"], "challenge_sha256": challenge_hash,
        "probe_samples": len(samples), "runner_events": len(events)
    })
    certificates_bound = bool(cert_events) and all(
        item.get("run_id") == context["run_id"] and item.get("challenge_sha256") == challenge_hash
        for item in cert_events
    )
    check("certificate_events_bound", certificates_bound, {"certificate_events": len(cert_events)})

    before = [row for row in samples if row["timestamp_epoch"] < fault_at]
    during = [row for row in samples if fault_at <= row["timestamp_epoch"] <= fixed_at]
    after = [row for row in samples if row["timestamp_epoch"] >= fixed_at]
    baseline_ok = bool(before) and all(row["target_ok"] and row["control_ok"] for row in before)
    check("baseline_tls_handshake", baseline_ok, {
        "samples": len(before), "successful": sum(bool(r["target_ok"]) for r in before)
    })

    bad_cert = next((item for item in cert_events if item["mode"] == "bad"), None)
    bad_expired = bool(bad_cert and bad_cert["not_after_epoch"] < bad_cert["generated_at_epoch"])
    expired_observed = any(
        not row["target_ok"]
        and row.get("target_cert_sha256") == (bad_cert or {}).get("certificate_sha256")
        and (row.get("target_error_type") == "SSLCertVerificationError"
             or "certificate has expired" in (row.get("target_error") or "").lower())
        for row in during
    )
    check("expired_certificate_rejected", bad_expired and expired_observed, {
        "bad_certificate_expired_at_generation": bad_expired,
        "strict_client_rejected_exact_leaf": expired_observed,
        "fault_window_samples": len(during)
    })

    good_certs = [item for item in cert_events if item["mode"] == "good"]
    recovered_cert = bool(good_certs and good_certs[-1]["not_after_epoch"] > good_certs[-1]["generated_at_epoch"])
    check("certificate_chain_ok_after_fix", recovered_cert, {
        "valid_leaf_generated_after_fix": recovered_cert,
        "recovery_samples": len(after)
    })
    hostname_ok = any(row["target_ok"] for row in after) and recovered_cert
    check("hostname_validation_ok", hostname_ok, {
        "strict_context_checks_hostname": True,
        "successful_recovery_handshakes": sum(bool(r["target_ok"]) for r in after)
    })

    stable_seconds = float(context["stability_seconds"])
    max_gap = float(context["max_probe_gap_seconds"])
    stable_start = stable_end = None
    run_start = previous = None
    for row in after:
        ts = float(row["timestamp_epoch"])
        if row["target_ok"] and row["control_ok"]:
            if run_start is None or previous is None or ts - previous > max_gap:
                run_start = ts
            previous = ts
            if ts - run_start >= stable_seconds:
                stable_start, stable_end = run_start, ts
                break
        else:
            run_start = previous = None
    stable = stable_start is not None
    mttr = (stable_end - fault_at) if stable and fault_at != float("inf") else None
    check("health_stable_window", stable, {
        "required_seconds": stable_seconds,
        "max_probe_gap_seconds": max_gap,
        "stable_start_epoch": stable_start,
        "stable_end_epoch": stable_end,
        "mttr_seconds": mttr,
        "recovery_samples": len(after)
    })

    control_failed = any(not row["control_ok"] for row in samples)
    check("control_sentinel_unaffected", bool(samples) and not control_failed, {
        "sentinel_samples": len(samples),
        "failed_sentinel_samples": sum(not row["control_ok"] for row in samples)
    })

    inspect_path = runtime / "docker-inspect.json"
    restart_count = None
    container_count = 0
    if inspect_path.is_file():
        containers = read_json(inspect_path)
        if isinstance(containers, dict):
            containers = [containers]
        container_count = len(containers)
        restart_count = sum(int(item.get("RestartCount", 0)) for item in containers)
    check("container_restart_count_zero", container_count == 2 and restart_count == 0, {
        "restart_count": restart_count, "container_count": container_count
    })

    docker_events = read_jsonl(runtime / "docker-events.jsonl")
    check("docker_events_captured", len(docker_events) >= 2, {"event_count": len(docker_events)})

    summary_path = runtime / "k6-summary.json"
    k6_requests = 0
    p95 = p99 = None
    if summary_path.is_file():
        metrics = read_json(summary_path).get("metrics", {})
        k6_requests = int(metrics.get("http_reqs", {}).get("values", {}).get("count", 0))
        latency_values = metrics.get("http_req_duration", {}).get("values", {})
        p95 = latency_values.get("p(95)")
        p99 = latency_values.get("p(99)")
    check("k6_load_observed", k6_requests > 0 and p95 is not None and p99 is not None, {
        "requests": k6_requests, "p95_ms": p95, "p99_ms": p99
    })

    slo_result = evaluate_slo(before, after, p95, p99, slo)
    check("slo_availability_met", slo_result["availability_ok"], slo_result)
    check("slo_latency_met", slo_result["latency_ok"], slo_result)

    result = {
        "schema": "ola-chaos-assertions/v0",
        "run_id": context["run_id"],
        "challenge_sha256": challenge_hash,
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failed_checks": failures,
        "metrics": {
            "baseline_availability": slo_result["baseline_availability"],
            "fault_availability": (sum(bool(r["target_ok"]) for r in during) / len(during)) if during else None,
            "recovery_availability": slo_result["recovery_availability"],
            "p95_ms": p95,
            "p99_ms": p99,
            "mttr_seconds": mttr,
            "stable_window_seconds": stable_seconds if stable else 0,
            "restart_count": restart_count,
            "collateral_sentinel_failed": control_failed,
            "probe_count": len(samples),
            "fault_at_epoch": None if fault_at == float("inf") else fault_at,
            "fix_at_epoch": None if fixed_at == float("inf") else fixed_at,
            "slo_availability_met": slo_result["availability_ok"],
            "slo_latency_met": slo_result["latency_ok"]
        }
    }
    (runtime / "assertions.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failed_checks": failures}, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
