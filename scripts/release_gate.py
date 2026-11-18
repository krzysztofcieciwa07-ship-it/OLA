"""Exact pull-request identity binding for release evidence selection."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SHA1 = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_WORKFLOW_PATHS: dict[str, str] = {
    "Evidence Cryptography V4 Contract": ".github/workflows/evidence-cryptography-v4.yml",
    "OLA paid-order PostgreSQL contract": ".github/workflows/paid-order-postgres.yml",
    "Python package CI": ".github/workflows/python-package-conda.yml",
    "OLA Local Staging Rehearsal": ".github/workflows/staging-rehearsal.yml",
    "Nina TDD": ".github/workflows/nina-tdd.yml",
    "NINA Parallel DAG Gate": ".github/workflows/nina-parallel-dag.yml",
    "OLA Supply Chain Evidence Gate": ".github/workflows/supply-chain-evidence.yml",
    "OLA CodeQL": ".github/workflows/codeql.yml",
    "OLA DI-OS Product Gate": ".github/workflows/ola-product-gate.yml",
    "OLA 12h Autonomous Evidence Flow": ".github/workflows/ola-12h-autoflow.yml",
    "OLA Decision Evidence Gate": ".github/workflows/decision-evidence-gate.yml",
    "Revenue Surface Gate": ".github/workflows/revenue-surface.yml",
    "OLA E2E Gate": ".github/workflows/e2e.yml",
    "Evidence Graph v0.1": ".github/workflows/evidence-graph.yml",
    "Real LLM Ollama Runtime Gate": ".github/workflows/ollama-real-runtime.yml",
    "Provenance Mutation Gate": ".github/workflows/provenance-mutation.yml",
    "Provenance Gate Final": ".github/workflows/provenance-gate-final.yml",
    "Nina Igor Gate": ".github/workflows/nina-igor-gate.yml",
    "Nina Real Runtime Provenance Gate (OpenAI optional)": ".github/workflows/nina-real-runtime-provenance.yml",
    "OLA State Continuity and Stability": ".github/workflows/state-continuity.yml",
    "OLA Real Runtime Stress Gate": ".github/workflows/runtime-stress.yml",
}

REFERENCE_WORKFLOW_PATHS: dict[str, str] = {
    "OLA Frontier Baseline": ".github/workflows/frontier-baseline.yml",
}


def filter_pull_request_runs(
    runs: list[dict[str, Any]],
    *,
    pr_number: int,
    target_sha: str,
    base_ref: str,
    base_sha: str,
) -> list[dict[str, Any]]:
    """Keep only runs associated with this PR, exact head and exact base."""
    if type(pr_number) is not int or pr_number < 1:
        raise ValueError("invalid pull request number")
    if not isinstance(target_sha, str) or not _SHA1.fullmatch(target_sha):
        raise ValueError("invalid target source SHA")
    if not isinstance(base_sha, str) or not _SHA1.fullmatch(base_sha):
        raise ValueError("invalid pull request base SHA")
    if not isinstance(base_ref, str) or not base_ref:
        raise ValueError("invalid pull request base ref")
    if not isinstance(runs, list):
        raise ValueError("workflow runs must be a list")

    selected: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("event") != "pull_request" or run.get("head_sha") != target_sha:
            continue
        associations = run.get("pull_requests")
        if not isinstance(associations, list):
            continue
        for pr in associations:
            if not isinstance(pr, dict):
                continue
            head = pr.get("head")
            base = pr.get("base")
            if (
                pr.get("number") == pr_number
                and isinstance(head, dict)
                and head.get("sha") == target_sha
                and head.get("ref") == run.get("head_branch")
                and isinstance(base, dict)
                and base.get("ref") == base_ref
                and base.get("sha") == base_sha
            ):
                selected.append(run)
                break
    return selected




def filter_expected_workflow_paths(
    runs: list[dict[str, Any]],
    expected_paths: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Keep only named runs emitted by their canonical workflow file path."""
    if not isinstance(runs, list):
        raise ValueError("workflow runs must be a list")
    if not isinstance(expected_paths, Mapping) or not expected_paths:
        raise ValueError("expected workflow paths must be a nonempty mapping")

    normalized: dict[str, str] = {}
    for name, path in expected_paths.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("invalid expected workflow name")
        if (
            not isinstance(path, str)
            or not path.startswith(".github/workflows/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or not path.endswith((".yml", ".yaml"))
        ):
            raise ValueError("invalid expected workflow path")
        normalized[name] = path

    if len(set(normalized.values())) != len(normalized):
        raise ValueError("expected workflow paths must be unique")

    return [
        run for run in runs
        if isinstance(run, dict)
        and isinstance(run.get("name"), str)
        and run["name"] in normalized
        and run.get("path") == normalized[run["name"]]
    ]


def filter_main_runs(
    runs: list[dict[str, Any]],
    *,
    target_sha: str,
    allowed_events: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Keep only exact-SHA runs executed from main, never PR evidence."""
    if not isinstance(target_sha, str) or not _SHA1.fullmatch(target_sha):
        raise ValueError("invalid target source SHA")
    if not isinstance(runs, list):
        raise ValueError("workflow runs must be a list")
    events = allowed_events if allowed_events is not None else {"push", "workflow_dispatch", "schedule"}
    if not isinstance(events, set) or not events or not all(
        event in {"push", "workflow_dispatch", "schedule"} for event in events
    ):
        raise ValueError("invalid main workflow event allowlist")
    return [
        run for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == target_sha
        and run.get("head_branch") == "main"
        and run.get("event") in events
    ]
