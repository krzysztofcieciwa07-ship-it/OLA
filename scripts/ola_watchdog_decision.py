"""Exact-SHA health decision for the OLA 24x7 watchdog."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
SUCCESS_MAX_AGE = timedelta(hours=12)
ATTEMPT_COOLDOWN = timedelta(minutes=15)


def _parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_duration(value):
    if not isinstance(value, str) or not value:
        raise ValueError("duration must be a non-empty string")
    unit = value[-1]
    amount = int(value[:-1])
    if amount < 0:
        raise ValueError("duration must be non-negative")
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "s":
        return timedelta(seconds=amount)
    raise ValueError("duration suffix must be h, m, or s")


def decide_dispatch(
    target_sha,
    runs,
    now=None,
    success_max_age=SUCCESS_MAX_AGE,
    cooldown=ATTEMPT_COOLDOWN,
):
    """Return a fail-closed dispatch decision for runs bound to target_sha."""
    now = now or datetime.now(timezone.utc)
    exact = [run for run in runs if run.get("headSha") == target_sha]

    if any(run.get("status") in ACTIVE_STATUSES for run in exact):
        return {"dispatch": False, "reason": "active_exact_sha"}

    timestamped = [
        (run, _parse_timestamp(run.get("createdAt") or run.get("created_at")))
        for run in exact
    ]
    timestamped = [(run, timestamp) for run, timestamp in timestamped if timestamp]

    successes = [
        (run, timestamp)
        for run, timestamp in timestamped
        if run.get("status") == "completed" and run.get("conclusion") == "success"
    ]
    if successes:
        _, latest_success = max(successes, key=lambda item: item[1])
        age = now - latest_success
        if age <= success_max_age:
            return {"dispatch": False, "reason": "success_fresh"}
        success_stale = True
    else:
        success_stale = False

    if exact and not timestamped:
        return {"dispatch": False, "reason": "unknown_exact_sha_timestamp"}

    if timestamped:
        _, latest_attempt = max(timestamped, key=lambda item: item[1])
        if now - latest_attempt < cooldown:
            return {"dispatch": False, "reason": "attempt_cooldown"}

    if success_stale:
        return {"dispatch": True, "reason": "success_stale"}
    return {"dispatch": True, "reason": "no_exact_sha_success"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--runs-file", required=True)
    parser.add_argument("--max-success-age", default="12h")
    parser.add_argument("--cooldown", default="15m")
    args = parser.parse_args()

    payload = json.loads(Path(args.runs_file).read_text(encoding="utf-8"))
    runs = payload if isinstance(payload, list) else payload.get("workflow_runs", [])
    decision = decide_dispatch(
        args.target_sha,
        runs,
        success_max_age=_parse_duration(args.max_success_age),
        cooldown=_parse_duration(args.cooldown),
    )
    print(
        "FULL_FLOW="
        + ("DISPATCH" if decision["dispatch"] else "NOT_DISPATCH")
        + " reason="
        + decision["reason"]
        + " target_sha="
        + args.target_sha
    )
    return 0 if decision["dispatch"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
