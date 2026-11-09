#!/usr/bin/env python3
"""Presence-only check for OLA Development secrets.

This command never prints, hashes, validates, or otherwise discloses secret
values. It reports only PRESENT or MISSING for the two independent encryption
keys required by the Human Identity session and local bundle-storage paths.
"""
from __future__ import annotations

import json
import os
import sys


REQUIRED_SECRETS = (
    "OLA_HUMAN_SESSION_ENCRYPTION_KEY",
    "OLA_CUSTOMER_BUNDLE_STORAGE_KEY",
)


def collect_presence(environment: dict[str, str] | None = None) -> dict[str, str]:
    """Return only presence states; secret values are never copied to output."""
    env = os.environ if environment is None else environment
    return {
        name: "PRESENT" if bool(env.get(name)) else "MISSING"
        for name in REQUIRED_SECRETS
    }


def main() -> int:
    checks = collect_presence()
    result = {
        "scope": "development_secret_presence_only",
        "values_exposed": False,
        "checks": checks,
        "status": "READY" if all(
            state == "PRESENT" for state in checks.values()
        ) else "BLOCKED",
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
