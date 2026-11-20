from datetime import datetime, timedelta, timezone

from scripts.ola_watchdog_decision import decide_dispatch


TARGET = "a" * 40
OTHER = "b" * 40
NOW = datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)


def run(sha, status, conclusion, age_minutes):
    created = NOW - timedelta(minutes=age_minutes)
    return {
        "headSha": sha,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created.isoformat().replace("+00:00", "Z"),
    }


def test_fresh_success_on_exact_sha_suppresses_dispatch():
    result = decide_dispatch(TARGET, [run(TARGET, "completed", "success", 300)], now=NOW)
    assert result["dispatch"] is False
    assert result["reason"] == "success_fresh"


def test_success_on_another_sha_does_not_suppress_dispatch():
    result = decide_dispatch(OTHER, [run(TARGET, "completed", "success", 300)], now=NOW)
    assert result["dispatch"] is True
    assert result["reason"] == "no_exact_sha_success"


def test_exact_sha_success_older_than_12_hours_dispatches():
    result = decide_dispatch(TARGET, [run(TARGET, "completed", "success", 13 * 60)], now=NOW)
    assert result["dispatch"] is True
    assert result["reason"] == "success_stale"


def test_active_exact_sha_run_suppresses_duplicate_dispatch():
    result = decide_dispatch(TARGET, [run(TARGET, "in_progress", None, 20)], now=NOW)
    assert result["dispatch"] is False
    assert result["reason"] == "active_exact_sha"


def test_recent_cancelled_attempt_is_cooldown_not_duplicate_dispatch():
    result = decide_dispatch(TARGET, [run(TARGET, "completed", "cancelled", 5)], now=NOW)
    assert result["dispatch"] is False
    assert result["reason"] == "attempt_cooldown"


def test_failed_exact_sha_run_dispatches_after_cooldown():
    result = decide_dispatch(TARGET, [run(TARGET, "completed", "failure", 20)], now=NOW)
    assert result["dispatch"] is True
    assert result["reason"] == "no_exact_sha_success"
