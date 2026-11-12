"""Fail-closed check of OLA's exact-source release evidence before GHCR publication."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REQUIRED_EXACT = (
    "OLA FINAL PRODUCTION GATE",
    "Nina TDD",
    "NINA Parallel DAG Gate",
    "OLA Supply Chain Evidence Gate",
    "OLA CodeQL",
    "OLA DI-OS Product Gate",
    "NINA IGOR Ollama Full Flow",
    "OLA Decision Evidence Gate",
    "Revenue Surface Gate",
    "OLA E2E Gate",
    "Evidence Graph v0.1",
    "Real LLM Ollama Runtime Gate",
    "Provenance Mutation Gate",
    "Provenance Gate Final",
    "Nina Igor Gate",
    "Nina Real Runtime Provenance Gate (OpenAI optional)",
    "OLA State Continuity and Stability",
    "OLA Real Runtime Stress Gate",
    "Python package CI",
)
REFERENCE_GATES = ("OLA Frontier Baseline",)
IGOR_JOB_NAME = "igor-independent-ollama / igor-ollama"


class ReleaseGateError(RuntimeError):
    """Raised when release evidence is failed, unavailable or inconsistent."""


def _newest_by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    newest: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        old = newest.get(name)
        if old is None or str(item.get("created_at", "")) > str(old.get("created_at", "")):
            newest[name] = item
    return newest


def evaluate_release_gates(*, expected_sha: str, exact_runs: list[dict[str, Any]],
                           reference_runs: list[dict[str, Any]],
                           igor_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    exact, reference = _newest_by_name(exact_runs), _newest_by_name(reference_runs)
    missing: list[str] = []
    pending: dict[str, Any] = {}
    failed: dict[str, Any] = {}
    observed: dict[str, Any] = {}

    for name in REQUIRED_EXACT:
        run = exact.get(name)
        observed[name] = run
        if run is None:
            missing.append(name)
        elif run.get("head_sha") != expected_sha:
            failed[name] = {"reason": "source_sha_mismatch", "observed_sha": run.get("head_sha")}
        elif run.get("status") != "completed":
            pending[name] = {"status": run.get("status"), "id": run.get("id")}
        elif run.get("conclusion") != "success":
            failed[name] = {"reason": "non_success_conclusion", "conclusion": run.get("conclusion")}

    for name in REFERENCE_GATES:
        run = reference.get(name)
        observed["reference:" + name] = run
        if run is None:
            missing.append("reference:" + name)
        elif run.get("status") != "completed":
            pending["reference:" + name] = {"status": run.get("status"), "id": run.get("id")}
        elif run.get("conclusion") != "success":
            failed["reference:" + name] = {"reason": "non_success_conclusion", "conclusion": run.get("conclusion")}

    igor = next((job for job in igor_jobs if job.get("name") == IGOR_JOB_NAME), None)
    observed["IGOR Independent Ollama Evidence Gate"] = igor
    if igor is None:
        pending["IGOR Independent Ollama Evidence Gate"] = {"status": "missing_job"}
    elif igor.get("status") != "completed":
        pending["IGOR Independent Ollama Evidence Gate"] = {"status": igor.get("status"), "id": igor.get("id")}
    elif igor.get("conclusion") != "success":
        failed["IGOR Independent Ollama Evidence Gate"] = {
            "reason": "non_success_conclusion", "conclusion": igor.get("conclusion")
        }

    status = "BLOCKED" if failed else ("PENDING" if missing or pending else "VERIFIED")
    return {
        "schema": "ola-release-gate-status/v1",
        "status": status,
        "expected_source_sha": expected_sha,
        "required_exact_gates": list(REQUIRED_EXACT),
        "reference_gates": list(REFERENCE_GATES),
        "observed": observed,
        "missing": sorted(missing),
        "pending": pending,
        "failed": failed,
    }


def _get_json(url: str, token: str) -> dict[str, Any]:
    request = Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ola-release-gate/1.0",
    })
    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ReleaseGateError("GitHub evidence API request failed: " + str(exc)) from exc
    if not isinstance(data, dict):
        raise ReleaseGateError("GitHub evidence API returned a non-object response")
    return data


def verify_release_gates(*, repository: str, expected_sha: str, token: str,
                         timeout_seconds: int = 1800, poll_seconds: int = 15) -> dict[str, Any]:
    if not repository or repository.count("/") != 1:
        raise ValueError("repository must use owner/repository form")
    if len(expected_sha) != 40 or any(c not in "0123456789abcdef" for c in expected_sha):
        raise ValueError("expected_sha must be a lowercase full 40-character Git SHA")
    if not token:
        raise ValueError("GitHub token is required")
    if timeout_seconds < 1 or poll_seconds < 1:
        raise ValueError("timeout_seconds and poll_seconds must be positive")

    base = "https://api.github.com/repos/" + repository
    exact_url = base + "/actions/runs?" + urlencode({"head_sha": expected_sha, "per_page": 100})
    reference_url = base + "/actions/runs?" + urlencode({"branch": "main", "event": "push", "per_page": 100})
    deadline = time.monotonic() + timeout_seconds
    attempt = 0

    while True:
        attempt += 1
        exact_data, reference_data = _get_json(exact_url, token), _get_json(reference_url, token)
        exact_runs, reference_runs = exact_data.get("workflow_runs", []), reference_data.get("workflow_runs", [])
        if not isinstance(exact_runs, list) or not isinstance(reference_runs, list):
            raise ReleaseGateError("GitHub evidence API returned malformed workflow run lists")

        nina = _newest_by_name(exact_runs).get("NINA IGOR Ollama Full Flow")
        igor_jobs: list[dict[str, Any]] = []
        if nina and isinstance(nina.get("id"), int):
            jobs_data = _get_json(base + "/actions/runs/" + str(nina["id"]) + "/jobs?per_page=100", token)
            jobs = jobs_data.get("jobs", [])
            if not isinstance(jobs, list):
                raise ReleaseGateError("GitHub jobs API returned a malformed jobs list")
            igor_jobs = jobs

        result = evaluate_release_gates(
            expected_sha=expected_sha, exact_runs=exact_runs,
            reference_runs=reference_runs, igor_jobs=igor_jobs,
        )
        print(json.dumps({"attempt": attempt, **result}, sort_keys=True), flush=True)
        if result["status"] == "VERIFIED":
            return result
        if result["status"] == "BLOCKED":
            raise ReleaseGateError("one or more required release evidence gates failed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReleaseGateError("timed out waiting for all required exact-source release gates")
        time.sleep(min(poll_seconds, remaining))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY"), required=os.getenv("GITHUB_REPOSITORY") is None)
    parser.add_argument("--source-sha", default=os.getenv("GITHUB_SHA"), required=os.getenv("GITHUB_SHA") is None)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--output", default="ola-release-gate-status.json")
    args = parser.parse_args(argv)
    try:
        result = verify_release_gates(
            repository=args.repository, expected_sha=args.source_sha,
            token=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "",
            timeout_seconds=args.timeout_seconds, poll_seconds=args.poll_seconds,
        )
        with open(args.output, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\\n")
    except (ValueError, ReleaseGateError, OSError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 1
    print("ALL_REQUIRED_RELEASE_GATES=VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
