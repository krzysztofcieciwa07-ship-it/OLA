"""Exact pull-request identity binding for release evidence selection."""
from __future__ import annotations

import re
from typing import Any

_SHA1 = re.compile(r"^[0-9a-f]{40}$")


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
