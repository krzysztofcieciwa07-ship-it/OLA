#!/usr/bin/env python3
"""Run OLA specialist checks and assemble commit-bound evidence reports.

This is a CI coordinator, not a general-purpose shell executor. Every command
is fixed in AGENT_CHECKS; callers cannot supply arbitrary commands or tools.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

AGENT_ORDER = (
    "tester",
    "architecture",
    "performance",
    "security",
    "legal",
)
VALID_AGENT_STATUSES = frozenset({"PASS", "FAIL", "REVIEW"})

LEGAL_REQUIRED_DOCS = (
    "docs/legal/privacy-notice.md",
    "docs/legal/terms-of-service.md",
    "docs/legal/data-processing-agreement.md",
    "docs/legal/subprocessors.md",
    "docs/legal/data-retention-and-deletion.md",
    "docs/legal/international-transfers.md",
    "docs/legal/ai-transparency.md",
)

AGENT_CHECKS = {
    "tester": (
        (
            "agent_runtime_and_lifecycle",
            (
                sys.executable, "-m", "pytest", "-q",
                "tests/test_agent_runtime.py",
                "tests/test_agent_runtime_finalization.py",
            ),
            900,
        ),
        (
            "orchestration_and_verification",
            (
                sys.executable, "-m", "pytest", "-q",
                "tests/test_nina.py",
                "tests/test_nina_igor_chain.py",
                "tests/test_igor_workflow.py",
                "tests/test_nina_workflow.py",
                "tests/test_workflow_engine.py",
            ),
            900,
        ),
    ),
    "architecture": (
        (
            "orchestration_contracts",
            (
                sys.executable, "-m", "pytest", "-q",
                "tests/test_nina_run_endpoint_contract.py",
                "tests/test_nina_workflow_gate.py",
                "tests/test_workflow_engine.py",
                "tests/test_release_source_binding.py",
            ),
            600,
        ),
        (
            "published_guarantees",
            (sys.executable, "scripts/verify_readme_claims.py"),
            300,
        ),
    ),
    "performance": (
        (
            "runtime_load_and_sli",
            (sys.executable, "scripts/stress_runtime.py"),
            360,
        ),
    ),
    "security": (
        (
            "execution_safety_and_tenant_boundary",
            (
                sys.executable, "-m", "pytest", "-q",
                "tests/test_execution_safety_gate.py",
                "tests/test_agent_run_safety_gate.py",
                "tests/test_independent_verifier_tamper.py",
                "tests/test_runtime_provenance.py",
                "tests/test_ollama_generation_budget.py",
            ),
            900,
        ),
    ),
}


class AgentTeamError(ValueError):
    """Raised when the evidence contract or invocation is invalid."""


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_commit(source_commit: str) -> None:
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
    ):
        raise AgentTeamError("source commit must be a full lowercase 40-character SHA-1")


def _validate_identity(agent_id: str, run_id: str, run_attempt: int) -> None:
    if agent_id not in AGENT_ORDER:
        raise AgentTeamError(f"unknown agent: {agent_id}")
    if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
        raise AgentTeamError("run id must be a non-empty string of at most 128 characters")
    if isinstance(run_attempt, bool) or not isinstance(run_attempt, int) or run_attempt < 1:
        raise AgentTeamError("run attempt must be a positive integer")


def build_agent_report(
    *,
    agent_id: str,
    source_commit: str,
    run_id: str,
    run_attempt: int,
    status: str,
    checks: list[dict[str, Any]],
    started_at: str,
    completed_at: str,
    duration_ms: int,
) -> dict[str, Any]:
    """Create a canonical, self-checksummed report for one specialist."""
    _validate_commit(source_commit)
    _validate_identity(agent_id, run_id, run_attempt)
    if status not in VALID_AGENT_STATUSES:
        raise AgentTeamError(f"invalid agent status: {status}")
    if not isinstance(checks, list) or any(not isinstance(item, dict) for item in checks):
        raise AgentTeamError("checks must be a list of objects")
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
        raise AgentTeamError("duration must be a non-negative integer")

    report = {
        "schema": "ola-agent-report-v1",
        "agent_id": agent_id,
        "source_commit": source_commit,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "checks": checks,
    }
    report["integrity_sha256"] = _sha256(_canonical_bytes(report))
    return report


def verify_report_integrity(report: Any) -> bool:
    """Verify the report checksum; this is integrity checking, not authentication."""
    if not isinstance(report, dict):
        return False
    digest = report.get("integrity_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    payload = {key: value for key, value in report.items() if key != "integrity_sha256"}
    try:
        expected = _sha256(_canonical_bytes(payload))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest, expected)


def aggregate_reports(
    reports: Iterable[dict[str, Any]],
    *,
    expected_source_commit: str,
    expected_run_id: str,
    expected_run_attempt: int,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Verify every role report and produce one fail-closed team manifest."""
    _validate_commit(expected_source_commit)
    if not isinstance(expected_run_id, str) or not expected_run_id:
        raise AgentTeamError("expected run id must be a non-empty string")
    if (
        isinstance(expected_run_attempt, bool)
        or not isinstance(expected_run_attempt, int)
        or expected_run_attempt < 1
    ):
        raise AgentTeamError("expected run attempt must be a positive integer")

    issues: list[str] = []
    review_agents: list[str] = []
    by_agent: dict[str, dict[str, Any]] = {}

    for report in reports:
        if not isinstance(report, dict):
            issues.append("non-object agent report encountered")
            continue
        agent_id = report.get("agent_id")
        if agent_id not in AGENT_ORDER:
            issues.append(f"unknown agent report: {agent_id!r}")
            continue
        if agent_id in by_agent:
            issues.append(f"duplicate agent report: {agent_id}")
            continue
        by_agent[agent_id] = report

        if not verify_report_integrity(report):
            issues.append(f"integrity check failed for {agent_id}")
        if report.get("schema") != "ola-agent-report-v1":
            issues.append(f"unsupported report schema for {agent_id}")
        if report.get("source_commit") != expected_source_commit:
            issues.append(f"source commit mismatch for {agent_id}")
        if report.get("run_id") != expected_run_id:
            issues.append(f"run id mismatch for {agent_id}")
        if report.get("run_attempt") != expected_run_attempt:
            issues.append(f"run attempt mismatch for {agent_id}")
        if report.get("status") not in VALID_AGENT_STATUSES:
            issues.append(f"invalid status for {agent_id}")
        elif report["status"] == "FAIL":
            issues.append(f"agent failed: {agent_id}")
        elif report["status"] == "REVIEW":
            review_agents.append(agent_id)

    missing_agents = [agent_id for agent_id in AGENT_ORDER if agent_id not in by_agent]
    if missing_agents:
        issues.extend(f"missing agent report: {agent_id}" for agent_id in missing_agents)

    if issues:
        overall_status = "BLOCKED"
    elif review_agents:
        overall_status = "REVIEW_REQUIRED"
    else:
        overall_status = "PASS"

    agent_summaries: dict[str, Any] = {}
    for agent_id in AGENT_ORDER:
        report = by_agent.get(agent_id)
        if report is None:
            agent_summaries[agent_id] = {"status": "MISSING", "report_sha256": None}
            continue
        agent_summaries[agent_id] = {
            "status": report.get("status"),
            "report_sha256": _sha256(_canonical_bytes(report)),
            "check_count": len(report.get("checks", [])) if isinstance(report.get("checks"), list) else 0,
            "source_commit": report.get("source_commit"),
            "run_id": report.get("run_id"),
            "run_attempt": report.get("run_attempt"),
        }

    all_received_reports_integrity_verified = (
        len(by_agent) == len(AGENT_ORDER)
        and all(verify_report_integrity(report) for report in by_agent.values())
    )
    all_received_reports_match_run_attempt = (
        len(by_agent) == len(AGENT_ORDER)
        and all(
            report.get("run_attempt") == expected_run_attempt
            for report in by_agent.values()
        )
    )

    manifest = {
        "schema": "ola-agent-team-manifest-v1",
        "source_commit": expected_source_commit,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "generated_at": generated_at or _utc_now(),
        "execution_order": list(AGENT_ORDER),
        "agents": agent_summaries,
        "missing_agents": missing_agents,
        "review_agents": review_agents,
        "issues": issues,
        "overall_status": overall_status,
        "orchestrator": {
            "agent_id": "orchestrator",
            "status": overall_status,
            "reports_expected": len(AGENT_ORDER),
            "reports_received": len(by_agent),
            "report_integrity_verified": all_received_reports_integrity_verified,
            "source_commit_consistent": (
                len(by_agent) == len(AGENT_ORDER)
                and not any("source commit mismatch" in item for item in issues)
            ),
            "run_attempt_consistent": all_received_reports_match_run_attempt,
            "report_authenticity": "NOT_ESTABLISHED_BY_SHA256",
            "production_deployment_authorized": False,
        },
    }
    manifest["integrity_sha256"] = _sha256(_canonical_bytes(manifest))
    return manifest


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _resolve_repo_path(raw_path: str, root: Path) -> Path:
    candidate = Path(raw_path)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise AgentTeamError("output and report paths must remain inside the repository") from exc
    return resolved


def _excerpt(value: str, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _command_check(
    check_id: str,
    command: tuple[str, ...],
    timeout_seconds: int,
    *,
    repo_root: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            list(command),
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        status = "PASS" if result.returncode == 0 else "FAIL"
        return_code = result.returncode
        error = None
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        status = "FAIL"
        return_code = None
        error = f"timeout after {timeout_seconds} seconds"
    except OSError as exc:
        stdout = ""
        stderr = ""
        status = "FAIL"
        return_code = None
        error = f"command could not start: {type(exc).__name__}"

    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    return {
        "check_id": check_id,
        "command": list(command),
        "status": status,
        "return_code": return_code,
        "duration_ms": elapsed_ms,
        "stdout_sha256": _sha256(stdout.encode("utf-8")),
        "stderr_sha256": _sha256(stderr.encode("utf-8")),
        "stdout_excerpt": _excerpt(stdout),
        "stderr_excerpt": _excerpt(stderr),
        "error": error,
    }


def _legal_coverage_check(repo_root: Path) -> dict[str, Any]:
    present = []
    missing = []
    empty = []
    for relative in LEGAL_REQUIRED_DOCS:
        path = repo_root / relative
        if not path.is_file():
            missing.append(relative)
        elif path.stat().st_size == 0:
            empty.append(relative)
        else:
            present.append(relative)
    return {
        "check_id": "legal_document_coverage",
        "status": "REVIEW",
        "required_documents": list(LEGAL_REQUIRED_DOCS),
        "present_documents": present,
        "missing_documents": missing,
        "empty_documents": empty,
        "note": (
            "File presence is not proof of legal adequacy. Human legal review, "
            "product/data-flow facts and jurisdiction-specific analysis remain required."
        ),
    }


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def run_agent(
    *,
    agent_id: str,
    source_commit: str,
    run_id: str,
    run_attempt: int,
    output_path: str,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Run one specialist using a fixed command allowlist and write its report."""
    _validate_commit(source_commit)
    _validate_identity(agent_id, run_id, run_attempt)
    output = _resolve_repo_path(output_path, repo_root)
    started_at = _utc_now()
    timer = time.perf_counter()
    checks: list[dict[str, Any]] = []

    try:
        actual_commit = _git_head(repo_root)
    except (OSError, subprocess.SubprocessError) as exc:
        actual_commit = ""
        checks.append({
            "check_id": "source_commit_binding",
            "status": "FAIL",
            "expected_source_commit": source_commit,
            "actual_source_commit": None,
            "error": f"git provenance unavailable: {type(exc).__name__}",
        })
    else:
        checks.append({
            "check_id": "source_commit_binding",
            "status": "PASS" if actual_commit == source_commit else "FAIL",
            "expected_source_commit": source_commit,
            "actual_source_commit": actual_commit,
        })

    if checks[0]["status"] == "PASS":
        environment = os.environ.copy()
        if agent_id == "legal":
            checks.append(_legal_coverage_check(repo_root))
        else:
            for check_id, command, timeout_seconds in AGENT_CHECKS[agent_id]:
                result = _command_check(
                    check_id,
                    command,
                    timeout_seconds,
                    repo_root=repo_root,
                    env=environment,
                )
                checks.append(result)

    if any(item.get("status") == "FAIL" for item in checks):
        status = "FAIL"
    elif any(item.get("status") == "REVIEW" for item in checks):
        status = "REVIEW"
    else:
        status = "PASS"

    report = build_agent_report(
        agent_id=agent_id,
        source_commit=source_commit,
        run_id=run_id,
        run_attempt=run_attempt,
        status=status,
        checks=checks,
        started_at=started_at,
        completed_at=_utc_now(),
        duration_ms=max(0, int((time.perf_counter() - timer) * 1000)),
    )
    _write_json(output, report)
    return report


def aggregate_from_directory(
    *,
    reports_dir: str,
    expected_source_commit: str,
    expected_run_id: str,
    expected_run_attempt: int,
    output_path: str,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    report_dir = _resolve_repo_path(reports_dir, repo_root)
    output = _resolve_repo_path(output_path, repo_root)
    reports: list[dict[str, Any]] = []
    for agent_id in AGENT_ORDER:
        path = report_dir / f"agent-{agent_id}.json"
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                reports.append(json.load(handle))
        except (OSError, json.JSONDecodeError):
            reports.append({"agent_id": agent_id, "status": "INVALID_REPORT_FILE"})
    manifest = aggregate_reports(
        reports,
        expected_source_commit=expected_source_commit,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )
    _write_json(output, manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OLA sequential agent-team audits.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one specialist agent")
    run_parser.add_argument("--agent", required=True, choices=AGENT_ORDER)
    run_parser.add_argument("--source-commit", required=True)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--run-attempt", required=True, type=int)
    run_parser.add_argument("--output", required=True)

    aggregate_parser = subparsers.add_parser("aggregate", help="verify and aggregate reports")
    aggregate_parser.add_argument("--reports-dir", required=True)
    aggregate_parser.add_argument("--source-commit", required=True)
    aggregate_parser.add_argument("--run-id", required=True)
    aggregate_parser.add_argument("--run-attempt", required=True, type=int)
    aggregate_parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            report = run_agent(
                agent_id=args.agent,
                source_commit=args.source_commit,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                output_path=args.output,
            )
            print(json.dumps(report, sort_keys=True, ensure_ascii=False))
            return 1 if report["status"] == "FAIL" else 0

        manifest = aggregate_from_directory(
            reports_dir=args.reports_dir,
            expected_source_commit=args.source_commit,
            expected_run_id=args.run_id,
            expected_run_attempt=args.run_attempt,
            output_path=args.output,
        )
        print(json.dumps(manifest, sort_keys=True, ensure_ascii=False))
        return 1 if manifest["overall_status"] == "BLOCKED" else 0
    except AgentTeamError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
