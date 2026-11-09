"""Presence-only Development secret check must never disclose values."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_development_secrets.py"
SECRET_NAMES = (
    "OLA_HUMAN_SESSION_ENCRYPTION_KEY",
    "OLA_CUSTOMER_BUNDLE_STORAGE_KEY",
)


def _run_with_environment(values: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for name in SECRET_NAMES:
        environment.pop(name, None)
    environment.update(values)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_presence_check_reports_only_names_and_states():
    sentinels = {
        SECRET_NAMES[0]: "SESSION_SECRET_SENTINEL_DO_NOT_PRINT",
        SECRET_NAMES[1]: "STORAGE_SECRET_SENTINEL_DO_NOT_PRINT",
    }

    result = _run_with_environment(sentinels)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "scope": "development_secret_presence_only",
        "values_exposed": False,
        "checks": {
            SECRET_NAMES[0]: "PRESENT",
            SECRET_NAMES[1]: "PRESENT",
        },
        "status": "READY",
    }
    assert "SESSION_SECRET_SENTINEL_DO_NOT_PRINT" not in result.stdout
    assert "STORAGE_SECRET_SENTINEL_DO_NOT_PRINT" not in result.stdout
    assert result.stderr == ""


def test_presence_check_fails_closed_when_one_secret_is_missing():
    sentinel = "SESSION_SECRET_SENTINEL_DO_NOT_PRINT"
    result = _run_with_environment({SECRET_NAMES[0]: sentinel})

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["checks"] == {
        SECRET_NAMES[0]: "PRESENT",
        SECRET_NAMES[1]: "MISSING",
    }
    assert sentinel not in result.stdout
    assert result.stderr == ""
