#!/usr/bin/env python3
"""Fail-closed exact-source watchdog for the OLA 12h evidence workflow."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import selectors
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ACTIVE_STATUSES = {"queued", "pending", "in_progress", "waiting", "requested"}
FRESHNESS_SECONDS = 900
MAX_ARTIFACT_ARCHIVE_BYTES = 256 * 1024 * 1024
FLOW_WORKFLOW = "ola-12h-autoflow.yml"


def is_allowed_dispatch(event_name: str, git_ref: str) -> bool:
    """Allow scheduled runs and manual runs bound to the current main ref."""
    return event_name != "workflow_dispatch" or git_ref == "refs/heads/main"


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
    # updatedAt reflects completion, whereas createdAt can make a long-running
    # successful flow appear stale immediately after it finishes.
    freshness_anchor = run.get("updatedAt") or run.get("completedAt") or run.get("createdAt")
    age = max(0.0, now_epoch - _timestamp(freshness_anchor))
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


def download_and_verify_artifact_archive(
    repository: str,
    artifact_id: int,
    expected_digest: str,
    expected_size_bytes: int,
    destination: str | Path,
) -> tuple[bool, str]:
    """Stream a bounded GitHub artifact ZIP, verify its API digest, then extract safely."""
    target = Path(destination)
    archive_path = target.parent / "ola-auto-evidence-artifact.zip"
    target.mkdir(parents=True, exist_ok=True)

    if (type(expected_size_bytes) is not int or expected_size_bytes < 1
            or expected_size_bytes > MAX_ARTIFACT_ARCHIVE_BYTES):
        return False, "aggregator_artifact_archive_size_limit"
    if not expected_digest.startswith("sha256:"):
        return False, "aggregator_artifact_digest_missing"
    expected_hex = expected_digest.removeprefix("sha256:").lower()
    if len(expected_hex) != 64 or any(ch not in "0123456789abcdef" for ch in expected_hex):
        return False, "aggregator_artifact_digest_invalid"

    command = [
        "gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"
    ]
    process: subprocess.Popen[bytes] | None = None

    def stop_child() -> None:
        if process is None:
            return
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if process.stdout is None:
            raise OSError("artifact download stdout unavailable")

        bytes_written = 0
        oversized = False
        deadline = time.monotonic() + 120.0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            with archive_path.open("wb") as archive_stream:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, 120)
                    if not selector.select(remaining):
                        raise subprocess.TimeoutExpired(command, 120)
                    chunk = os.read(
                        process.stdout.fileno(),
                        min(64 * 1024, expected_size_bytes - bytes_written + 1),
                    )
                    if not chunk:
                        break
                    if bytes_written + len(chunk) > expected_size_bytes:
                        oversized = True
                        break
                    archive_stream.write(chunk)
                    bytes_written += len(chunk)

        if oversized:
            stop_child()
            archive_path.unlink(missing_ok=True)
            return False, "aggregator_artifact_archive_size_mismatch"

        return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if return_code != 0:
            archive_path.unlink(missing_ok=True)
            return False, "aggregator_artifact_download_failed"
        if bytes_written != expected_size_bytes:
            archive_path.unlink(missing_ok=True)
            return False, "aggregator_artifact_archive_size_mismatch"
    except subprocess.TimeoutExpired:
        stop_child()
        archive_path.unlink(missing_ok=True)
        return False, "aggregator_artifact_download_timeout"
    except OSError:
        stop_child()
        archive_path.unlink(missing_ok=True)
        return False, "aggregator_artifact_download_failed"
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()

    digest = hashlib.sha256()
    with archive_path.open("rb") as archive_stream:
        for chunk in iter(lambda: archive_stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected_hex):
        archive_path.unlink(missing_ok=True)
        return False, "aggregator_artifact_archive_digest_mismatch"

    try:
        with zipfile.ZipFile(archive_path) as bundle:
            infos = bundle.infolist()
            if not infos or len(infos) > 2000:
                return False, "aggregator_artifact_archive_entry_limit"
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > 256 * 1024 * 1024:
                return False, "aggregator_artifact_archive_size_limit"

            seen_paths: set[str] = set()
            file_paths: set[str] = set()
            for info in infos:
                name = info.filename
                path = PurePosixPath(name)
                mode = (info.external_attr >> 16) & 0o170000
                raw_name = name[:-1] if name.endswith("/") else name
                raw_parts = raw_name.split("/") if raw_name else []
                if (
                    not name
                    or "\\" in name
                    or path.is_absolute()
                    or not path.parts
                    or any(part in {"", "."} for part in raw_parts)
                    or ".." in path.parts
                    or (path.parts and ":" in path.parts[0])
                    or mode == stat.S_IFLNK
                    or info.file_size > 128 * 1024 * 1024
                ):
                    return False, "aggregator_artifact_archive_unsafe_entry"

                # ZIP names such as "a/./b" and "a//b" normalize to the
                # same extraction path as "a/b". Reject aliases and file/
                # parent collisions before extractall can overwrite evidence.
                normalized = path.as_posix()
                if normalized in seen_paths:
                    return False, "aggregator_artifact_archive_unsafe_entry"
                if any(
                    parent.as_posix() in file_paths
                    for parent in path.parents
                    if parent.parts
                ):
                    return False, "aggregator_artifact_archive_unsafe_entry"
                is_directory = info.is_dir()
                if not is_directory and any(
                    existing.startswith(normalized + "/")
                    for existing in seen_paths
                ):
                    return False, "aggregator_artifact_archive_unsafe_entry"

                seen_paths.add(normalized)
                if not is_directory:
                    file_paths.add(normalized)
            bundle.extractall(target)
    except (zipfile.BadZipFile, RuntimeError, ValueError):
        return False, "aggregator_artifact_archive_invalid"

    return True, "verified"

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
        "aggregator_artifact_size_bytes": None,
        "aggregator_artifact_digest_verified": False,
        "aggregator_summary_sha256": None,
        "evidence_status": "UNKNOWN",
        "decision": "STOP",
        "action": "NONE",
        "reason": "watchdog_not_completed",
    }

    try:
        if not is_allowed_dispatch(
            os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("GITHUB_REF", ""),
        ):
            _block(report, "manual_dispatch_ref_not_main")
            report["evidence_status"] = "BLOCKED"
            return report

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
            "--json", "databaseId,status,conclusion,createdAt,updatedAt,headSha,headBranch",
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
        artifact_size = artifact.get("size_in_bytes")
        report["aggregator_artifact_size_bytes"] = artifact_size
        if type(artifact_size) is not int or not 1 <= artifact_size <= MAX_ARTIFACT_ARCHIVE_BYTES:
            _block(report, "aggregator_artifact_archive_size_limit")
            report["evidence_status"] = "BLOCKED"
            return report
        digest = str(artifact.get("digest") or "")
        if not digest.startswith("sha256:"):
            _block(report, "aggregator_artifact_digest_missing")
            report["evidence_status"] = "BLOCKED"
            return report

        try:
            with tempfile.TemporaryDirectory(prefix="ola-watchdog-evidence-") as directory:
                bundle_dir = Path(directory) / "bundle"
                archive_ok, archive_reason = download_and_verify_artifact_archive(
                    repository,
                    int(artifact["id"]),
                    digest,
                    artifact_size,
                    bundle_dir,
                )
                if not archive_ok:
                    _block(report, archive_reason)
                    report["evidence_status"] = "BLOCKED"
                    return report
                report["aggregator_artifact_digest_verified"] = True
                valid, reason, summary = verify_aggregator_bundle(bundle_dir, source_sha)
                if summary is not None:
                    summary_bytes = (bundle_dir / "ola-auto-evidence.json").read_bytes()
                    report["aggregator_summary_sha256"] = hashlib.sha256(summary_bytes).hexdigest()
        except (KeyError, TypeError, ValueError):
            _block(report, "aggregator_artifact_metadata_invalid")
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
