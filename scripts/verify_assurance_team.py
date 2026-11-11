#!/usr/bin/env python3
"""Independent stdlib-only verifier for OLA Assurance Agent Team artifacts."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


GENESIS_HASH = "0" * 64
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
VALID_STATUSES = {"PASS", "FAIL", "BLOCKED", "UNKNOWN"}


class VerificationError(Exception):
    pass


def canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def verify_event_stream(events, expected_commit, report):
    require(isinstance(events, list) and len(events) >= 2, "event stream is empty or malformed")
    report_events = report.get("events")
    require(report_events == events, "embedded report events differ from JSONL event stream")
    require(report.get("event_count") == len(events), "event count does not match report")

    run_id = report.get("run_id")
    require(isinstance(run_id, str) and run_id, "report run_id is missing")
    previous_hash = GENESIS_HASH
    active_role = None
    started_roles = []
    ended_roles = []
    run_start_count = 0
    run_end_count = 0

    for sequence, event in enumerate(events):
        require(isinstance(event, dict), f"event {sequence} is not an object")
        supplied_hash = event.get("event_hash")
        body = {key: value for key, value in event.items() if key != "event_hash"}
        require(body.get("sequence") == sequence, f"event sequence mismatch at {sequence}")
        require(body.get("run_id") == run_id, f"run_id mismatch at event {sequence}")
        require(body.get("previous_hash") == previous_hash, f"previous hash mismatch at event {sequence}")
        require(isinstance(body.get("timestamp"), str) and body["timestamp"], f"timestamp missing at event {sequence}")
        computed_hash = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        require(supplied_hash == computed_hash, f"event hash mismatch at sequence {sequence}")

        event_type = body.get("event_type")
        payload = body.get("payload")
        require(isinstance(payload, dict), f"event payload malformed at sequence {sequence}")

        if event_type == "run.start":
            run_start_count += 1
            require(sequence == 0, "run.start must be the first event")
            require(payload.get("source_commit") == expected_commit, "run.start source commit mismatch")
        elif event_type == "agent.start":
            role = payload.get("role")
            require(active_role is None, "specialist executions overlap")
            require(isinstance(role, str) and role, "agent.start role missing")
            require(payload.get("source_commit") == expected_commit, f"{role} source commit mismatch")
            active_role = role
            started_roles.append(role)
        elif event_type == "agent.end":
            role = payload.get("role")
            require(active_role is not None and role == active_role, "agent.end does not match the active specialist")
            require(payload.get("status") in VALID_STATUSES, f"{role} status is invalid")
            active_role = None
            ended_roles.append(role)
        elif event_type == "run.end":
            run_end_count += 1
            require(sequence == len(events) - 1, "run.end must be the final event")
            require(active_role is None, "run ended while a specialist was active")
            require(payload.get("source_commit") == expected_commit, "run.end source commit mismatch")
            require(payload.get("status") == report.get("status"), "run-end status differs from report")
        else:
            raise VerificationError(f"unrecognized lifecycle event: {event_type}")

        previous_hash = supplied_hash

    require(run_start_count == 1 and run_end_count == 1, "lifecycle must contain exactly one run.start and run.end")
    require(started_roles == ended_roles, "specialist lifecycle is incomplete")
    require(started_roles == report.get("coverage", {}).get("enabled"), "enabled roles differ from lifecycle")
    require(ended_roles == [item.get("role") for item in report.get("agent_results", [])], "agent results differ from lifecycle")

    start_payload = events[0]["payload"]
    require(start_payload.get("planned_roles") == report.get("coverage", {}).get("planned"), "planned role list mismatch")
    require(start_payload.get("enabled_roles") == report.get("coverage", {}).get("enabled"), "enabled role list mismatch")

    coverage = report.get("coverage", {})
    planned = coverage.get("planned")
    enabled = coverage.get("enabled")
    not_enabled = coverage.get("not_enabled")
    require(isinstance(planned, list) and isinstance(enabled, list) and isinstance(not_enabled, list), "coverage fields malformed")
    require(not_enabled == [role for role in planned if role not in enabled], "not-enabled role list is inconsistent")
    expected_coverage = "COMPLETE" if not not_enabled else "PARTIAL"
    require(coverage.get("coverage_status") == expected_coverage, "coverage status mismatch")

    statuses = [item.get("status") for item in report.get("agent_results", [])]
    require(all(status in VALID_STATUSES for status in statuses), "agent result status invalid")
    if "FAIL" in statuses:
        expected_status = "FAIL"
    elif "BLOCKED" in statuses:
        expected_status = "BLOCKED"
    elif "UNKNOWN" in statuses:
        expected_status = "UNKNOWN"
    else:
        expected_status = "PASS"
    require(report.get("status") == expected_status, "aggregate report status is inconsistent")
    require(report.get("event_chain_valid") is True, "report did not mark lifecycle as valid")


def verify_bundle(report_path, events_path, manifest_path, expected_commit):
    require(SHA_PATTERN.fullmatch(expected_commit or "") is not None, "expected commit must be a full lowercase 40-character SHA-1")

    report_bytes = Path(report_path).read_bytes()
    events_bytes = Path(events_path).read_bytes()
    manifest_text = Path(manifest_path).read_text(encoding="utf-8")

    report_digest = hashlib.sha256(report_bytes).hexdigest()
    events_digest = hashlib.sha256(events_bytes).hexdigest()
    entries = {}
    for line in manifest_text.splitlines():
        fields = line.split("  ", 1)
        require(len(fields) == 2, "manifest line is malformed")
        digest, filename = fields
        require(filename not in entries, "duplicate manifest entry")
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "manifest digest malformed")
        entries[filename] = digest
    require(set(entries) == {"team-report.json", "team-events.jsonl"}, "manifest file set mismatch")
    require(entries["team-report.json"] == report_digest, "report manifest digest mismatch")
    require(entries["team-events.jsonl"] == events_digest, "event manifest digest mismatch")

    try:
        report = json.loads(report_bytes)
        event_lines = events_bytes.decode("utf-8").splitlines()
        events = [json.loads(line) for line in event_lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"artifact JSON is invalid ({type(exc).__name__})") from None

    require(report.get("schema") == "ola-assurance-team-report-v1", "report schema mismatch")
    require(report.get("source_commit") == expected_commit, "report source commit does not match tested source")
    require(report.get("events_sha256") == events_digest, "report event-stream digest mismatch")
    verify_event_stream(events, expected_commit, report)
    return {
        "status": "VERIFIED",
        "source_commit": expected_commit,
        "report_sha256": report_digest,
        "events_sha256": events_digest,
        "event_count": len(events),
        "enabled_roles": report["coverage"]["enabled"],
        "not_enabled_roles": report["coverage"]["not_enabled"],
        "agent_status": report["status"],
        "coverage_status": report["coverage"]["coverage_status"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Independently verify the OLA assurance evidence bundle.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_bundle(args.report, args.events, args.manifest, args.expected_commit)
    except (OSError, VerificationError, ValueError, TypeError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
