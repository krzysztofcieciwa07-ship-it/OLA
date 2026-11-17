"""Exact-SHA Gitleaks scan-range policy and runner."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40
_SARIF_PATH = Path("gitleaks-exact-source-results.sarif")
_METADATA_PATH = Path("gitleaks-exact-scan.json")


def _require_sha(value: str | None, field: str) -> str:
    if not isinstance(value, str) or not _SHA1.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def build_scan_plan(
    event: str,
    target_sha: str,
    *,
    base_sha: str | None = None,
    merge_base: str | None = None,
    before_sha: str | None = None,
) -> dict[str, Any]:
    """Build a Gitleaks range ending at the immutable source SHA.

    A missing log option means a full-history scan. Incremental PR/push scans
    follow the first-parent chain and include each merge commit's first-parent
    diff, so merged side-branch changes are not silently omitted. The PR plan
    uses event base SHA and exact checked-out source SHA supplied by the workflow.
    """
    target = _require_sha(target_sha, "target source SHA")

    if event == "pull_request":
        base = _require_sha(base_sha, "pull request base SHA")
        ancestor = _require_sha(merge_base, "pull request merge-base SHA")
        if ancestor == target:
            return {
                "source_sha": target,
                "base_sha": base,
                "merge_base": ancestor,
                "before_sha": None,
                "scan_range": target,
                "log_opts": "--diff-merges=first-parent -1",
            }
        scan_range = f"{ancestor}..{target}"
        return {
            "source_sha": target,
            "base_sha": base,
            "merge_base": ancestor,
            "before_sha": None,
            "scan_range": scan_range,
            "log_opts": f"--first-parent --diff-merges=first-parent {scan_range}",
        }

    if event == "push":
        if before_sha in (None, "", _ZERO_SHA):
            return {
                "source_sha": target,
                "base_sha": None,
                "merge_base": None,
                "before_sha": before_sha or None,
                "scan_range": "FULL_HISTORY",
                "log_opts": None,
            }
        before = _require_sha(before_sha, "push before SHA")
        if before == target:
            return {
                "source_sha": target,
                "base_sha": None,
                "merge_base": None,
                "before_sha": before,
                "scan_range": target,
                "log_opts": "--diff-merges=first-parent -1",
            }
        scan_range = f"{before}..{target}"
        return {
            "source_sha": target,
            "base_sha": None,
            "merge_base": None,
            "before_sha": before,
            "scan_range": scan_range,
            "log_opts": f"--first-parent --diff-merges=first-parent {scan_range}",
        }

    if event in {"workflow_dispatch", "schedule"}:
        return {
            "source_sha": target,
            "base_sha": None,
            "merge_base": None,
            "before_sha": None,
            "scan_range": "FULL_HISTORY",
            "log_opts": None,
        }

    raise ValueError(f"unsupported Gitleaks event: {event}")


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    target_sha = _require_sha(os.environ.get("EXPECTED_SOURCE_SHA"), "expected source SHA")
    checked_out_sha = _git("rev-parse", "HEAD")
    if checked_out_sha != target_sha:
        raise RuntimeError(f"checkout SHA {checked_out_sha} != expected source SHA {target_sha}")

    base_sha = os.environ.get("PR_BASE_SHA") or None
    before_sha = os.environ.get("BEFORE_SHA") or None
    merge_base = None
    if event == "pull_request":
        base = _require_sha(base_sha, "pull request base SHA")
        _git("cat-file", "-e", f"{base}^{{commit}}")
        merge_base = _git("merge-base", base, target_sha)
        _require_sha(merge_base, "computed merge-base SHA")
    elif event == "push" and before_sha not in (None, "", _ZERO_SHA):
        before = _require_sha(before_sha, "push before SHA")
        _git("cat-file", "-e", f"{before}^{{commit}}")
        _git("merge-base", "--is-ancestor", before, target_sha)

    plan = build_scan_plan(
        event,
        target_sha,
        base_sha=base_sha,
        merge_base=merge_base,
        before_sha=before_sha,
    )
    binary = shutil.which("gitleaks")
    if not binary:
        raise RuntimeError("Gitleaks binary was not installed by the pinned bootstrap action")
    version_result = subprocess.run([binary, "version"], check=False, capture_output=True, text=True)
    if version_result.returncode != 0:
        raise RuntimeError("unable to determine Gitleaks version")

    command = [
        binary,
        "detect",
        "--redact",
        "-v",
        "--exit-code=2",
        "--report-format=sarif",
        f"--report-path={_SARIF_PATH}",
        "--log-level=debug",
    ]
    if plan["log_opts"]:
        command.append(f"--log-opts={plan['log_opts']}")

    print(f"GITLEAKS_EXACT_SOURCE_SHA={target_sha}")
    print(f"GITLEAKS_EXACT_SCAN_RANGE={plan['scan_range']}")
    print(f"GITLEAKS_EXACT_LOG_OPTS={plan['log_opts'] or 'FULL_HISTORY'}")
    scan_result = subprocess.run(command, check=False)

    findings_count = None
    sarif_digest = _sha256(_SARIF_PATH)
    if sarif_digest is not None:
        try:
            sarif = json.loads(_SARIF_PATH.read_text(encoding="utf-8"))
            sarif_runs = sarif.get("runs")
            if isinstance(sarif_runs, list) and sarif_runs:
                findings_count = sum(len(run.get("results", [])) for run in sarif_runs)
        except (OSError, json.JSONDecodeError, TypeError):
            findings_count = None

    passed = scan_result.returncode == 0 and findings_count == 0 and sarif_digest is not None
    metadata = {
        "schema_version": 1,
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "event": event,
        "pr_number": os.environ.get("PR_NUMBER") or None,
        "source_sha": target_sha,
        "checked_out_sha": checked_out_sha,
        "base_sha": plan["base_sha"],
        "merge_base": plan["merge_base"],
        "before_sha": plan["before_sha"],
        "scan_range": plan["scan_range"],
        "log_opts": plan["log_opts"],
        "gitleaks_version": version_result.stdout.strip(),
        "findings_count": findings_count,
        "sarif_sha256": sarif_digest,
        "legacy_pr_api_scan_outcome": os.environ.get("LEGACY_GITLEAKS_OUTCOME"),
        "exit_code": scan_result.returncode,
        "result": "PASS" if passed else "FAIL",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _METADATA_PATH.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, sort_keys=True))

    if not passed:
        return scan_result.returncode or 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1)
