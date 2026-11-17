#!/usr/bin/env python3
"""Fail-closed exact-source watchdog for the OLA 12h evidence workflow."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested"}
FRESHNESS_SECONDS = 900
FLOW_WORKFLOW = "ola-12h-autoflow.yml"


def _timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _latest(items: list[dict[str, Any]]) -> dict[str, Any]:
    return max(items, key=lambda item: _timestamp(item.get("createdAt")))


def choose_flow_action(
    runs: list[dict[str, Any]], source_sha: str
) -> dict[str, Any]:
    """Choose a safe action using only main-branch runs and exact source SHA."""
    main_runs = [item for item in runs if item.get("headBranch") == "main"]
    active = [
        item for item in main_runs
        if str(item.get("status", "")).lower() in ACTIVE_STATUSES
    ]
    if active:
        return {
            "action": "WAIT",
            "reason": "active_main_flow",
            "run": _latest(active),
        }

    exact = [item for item in main_runs if item.get("headSha") == source_sha]
    if not exact:
        return {
            "action": "DISPATCH",
            "reason": "no_exact_sha_run",
            "run": None,
        }

    selected = _latest(exact)
    status = str(selected.get("status", "")).lower()
    conclusion = str(selected.get("conclusion", "")).lower()
    if status in ACTIVE_STATUSES:
        return {"action": "WAIT", "reason": "exact_sha_flow_active", "run": selected}
    if status != "completed" or conclusion != "success":
        return {
            "action": "BLOCKED",
            "reason": "exact_sha_run_failed",
            "run": selected,
        }
    return {"action": "VERIFY", "reason": "exact_sha_run_success", "run": selected}


def decide_verified_flow(
    run: dict[str, Any],
    *,
    evidence_valid: bool,
    now_epoch: float,
    freshness_seconds: int = FRESHNESS_SECONDS,
) -> dict[str, str]:
    """Decide whether verified exact-SHA evidence is fresh enough."""
    if not evidence_valid:
        return {"action": "BLOCKED", "reason": "aggregator_evidence_not_verified"}
    age = max(0.0, now_epoch - _timestamp(run.get("createdAt")))
    if age >= freshness_seconds:
        return {"action": "DISPATCH", "reason": "verified_flow_stale"}
    return {"action": "HEALTHY", "reason": "verified_exact_sha_flow_fresh"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def verify_aggregator_bundle(
    directory: str | Path, source_sha: str
) -> tuple[bool, str, dict[str, Any] | None]:
    """Verify the aggregator's own checksum and fail-closed V3 claims."""
    root = Path(directory)
    summary_path = root / "ola-auto-evidence.json"
    checksum_path = root / "ola-auto-evidence.sha256"
    try:
        raw = summary_path.read_bytes()
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False, "aggregator_files_missing", None

    if len(lines) != 1:
        return False, "checksum_manifest_invalid", None
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != "ola-auto-evidence.json":
        return False, "checksum_manifest_invalid", None

    actual_digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_digest, fields[0].lower()):
        return False, "summary_checksum_mismatch", None

    try:
        summary = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False, "summary_json_invalid", None
    if not isinstance(summary, dict):
        return False, "summary_json_invalid", None
    if summary.get("source_commit") != source_sha:
        return False, "source_sha_mismatch", summary
    if summary.get("schema") != "ola-auto-evidence-v3":
        return False, "unsupported_aggregator_schema", summary
    if summary.get("provider") != "ollama" or summary.get("openai_required") is not False:
        return False, "provider_policy_mismatch", summary

    required = (
        summary.get("preflight") == "success"
        and summary.get("real_ollama_full_flow") == "success"
        and summary.get("preflight_artifact_integrity") == "VERIFIED"
        and summary.get("ollama_artifact_integrity") == "VERIFIED"
        and summary.get("independent_igor_artifact_integrity") == "VERIFIED"
        and summary.get("status") == "RUNTIME_CHAIN_VERIFIED"
        and summary.get("verified_claim") is True
        and summary.get("human_gate") == "required_for_terminal_execution"
        and summary.get("fail_closed") is True
    )
    if not required:
        return False, "evidence_not_verified", summary
    return True, "verified", summary


def _gh_json(arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["gh", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _dispatch(report: dict[str, Any], reason: str) -> None:
    completed = subprocess.run(
        ["gh", "workflow", "run", FLOW_WORKFLOW, "--ref", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    report["decision"] = "CONTINUE"
    report["action"] = "DISPATCHED"
    report["reason"] = reason
    report["dispatch_reference"] = completed.stdout.strip()


def _block(report: dict[str, Any], reason: str) -> None:
    report["decision"] = "HUMAN_GATE"
    report["action"] = "NONE"
    report["reason"] = reason


def run_watchdog() -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    initial_path = Path("watchdog-evidence.json")
    if initial_path.is_file():
        try:
            initial_report = json.loads(initial_path.read_text(encoding="utf-8"))
            started = initial_report.get("run.start") or started
        except (OSError, json.JSONDecodeError):
            pass
    report: dict[str, Any] = {
        "schema": "ola-24x7-watchdog-evidence-v1",
        "run.start": started,
        "run.end": None,
        "source_sha": None,
        "flow_run_id": None,
        "flow_sha": None,
        "flow_conclusion": None,
        "aggregator_artifact_id": None,
        "aggregator_artifact_digest": None,
        "aggregator_summary_sha256": None,
        "evidence_status": "UNKNOWN",
        "decision": "STOP",
        "action": "NONE",
        "reason": "watchdog_not_completed",
    }

    try:
        source_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        report["source_sha"] = source_sha
        repository = os.environ["GITHUB_REPOSITORY"]

        runs = _gh_json([
            "run", "list",
            "--workflow", FLOW_WORKFLOW,
            "--branch", "main",
            "--limit", "100",
            "--json", "databaseId,status,conclusion,createdAt,headSha,headBranch",
        ])
        selection = choose_flow_action(runs, source_sha)
        selected = selection.get("run")
        if selected:
            report["flow_run_id"] = selected.get("databaseId")
            report["flow_sha"] = selected.get("headSha")
            report["flow_conclusion"] = selected.get("conclusion")

        if selection["action"] == "WAIT":
            report["decision"] = "CONTINUE"
            report["action"] = "WAIT"
            report["reason"] = selection["reason"]
            return report
        if selection["action"] == "BLOCKED":
            _block(report, selection["reason"])
            report["evidence_status"] = "BLOCKED"
            return report
        if selection["action"] == "DISPATCH":
            _dispatch(report, selection["reason"])
            return report

        run_id = str(selected["databaseId"])
        jobs_payload = _gh_json([
            "api", f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        ])
        classify = next(
            (job for job in jobs_payload.get("jobs", []) if job.get("name") == "classify"),
            None,
        )
        if not classify or classify.get("conclusion") != "success":
            _block(report, "classify_job_not_successful")
            report["evidence_status"] = "BLOCKED"
            return report

        artifacts_payload = _gh_json([
            "api", f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        ])
        artifact_name = f"ola-auto-evidence-{source_sha}"
        artifact = next(
            (item for item in artifacts_payload.get("artifacts", [])
             if item.get("name") == artifact_name),
            None,
        )
        if not artifact or artifact.get("expired") is True:
            _block(report, "aggregator_artifact_missing_or_expired")
            report["evidence_status"] = "BLOCKED"
            return report

        report["aggregator_artifact_id"] = artifact.get("id")
        report["aggregator_artifact_digest"] = artifact.get("digest")
        digest = str(artifact.get("digest") or "")
        if not digest.startswith("sha256:"):
            _block(report, "aggregator_artifact_digest_missing")
            report["evidence_status"] = "BLOCKED"
            return report

        try:
            with tempfile.TemporaryDirectory(prefix="ola-watchdog-evidence-") as directory:
                subprocess.run(
                    [
                        "gh", "run", "download", run_id,
                        "--name", artifact_name,
                        "--dir", directory,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                valid, reason, summary = verify_aggregator_bundle(directory, source_sha)
                if summary is not None:
                    summary_bytes = (Path(directory) / "ola-auto-evidence.json").read_bytes()
                    report["aggregator_summary_sha256"] = hashlib.sha256(summary_bytes).hexdigest()
        except subprocess.CalledProcessError:
            _block(report, "aggregator_artifact_download_failed")
            report["evidence_status"] = "BLOCKED"
            return report

        if not valid:
            _block(report, reason)
            report["evidence_status"] = "BLOCKED"
            return report

        report["evidence_status"] = "VERIFIED"
        freshness = decide_verified_flow(
            selected,
            evidence_valid=True,
            now_epoch=time.time(),
        )
        if freshness["action"] == "DISPATCH":
            _dispatch(report, freshness["reason"])
        else:
            report["decision"] = "CONTINUE"
            report["action"] = "NONE"
            report["reason"] = freshness["reason"]
        return report

    except subprocess.CalledProcessError as exc:
        report["decision"] = "STOP"
        report["action"] = "NONE"
        report["reason"] = "github_or_git_command_failed"
        report["error_type"] = type(exc).__name__
        report["error_exit_code"] = exc.returncode
        return report
    except Exception as exc:  # fail closed; do not expose command output or credentials
        report["decision"] = "STOP"
        report["action"] = "NONE"
        report["reason"] = "watchdog_internal_error"
        report["error_type"] = type(exc).__name__
        return report
    finally:
        report["run.end"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        Path("watchdog-evidence.json").write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as output:
                output.write(f"decision={report['decision']}\n")
                output.write(f"reason={report['reason']}\n")
                output.write(f"action={report['action']}\n")


if __name__ == "__main__":
    result = run_watchdog()
    print(json.dumps(result, sort_keys=True))
