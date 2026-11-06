"""Read build-time source identity; runtime environment is not authoritative."""
import json
import os
from pathlib import Path
import re

_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def runtime_source_commit(*, require_build_info=None, build_info_path=None):
    """Return source SHA embedded at image build time, fail closed in strict mode.

    OLA_RUNTIME_COMMIT is a compatibility fallback for local/legacy test runs
    only. When strict mode is enabled, missing or malformed build metadata
    returns None and the environment variable is never trusted.
    """
    strict = (
        os.getenv("OLA_REQUIRE_BUILD_INFO", "0") == "1"
        if require_build_info is None else bool(require_build_info)
    )
    path = Path(build_info_path or os.getenv(
        "OLA_BUILD_INFO_PATH", "/app/ola-build-info.json"
    ))
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = None
        if isinstance(data, dict) and data.get("schema") == "ola-build-info/v1":
            commit = data.get("source_commit")
            if isinstance(commit, str) and _COMMIT.fullmatch(commit):
                return commit
    if strict:
        return None
    legacy = os.getenv("OLA_RUNTIME_COMMIT")
    # Non-strict local compatibility only; /readyz and strict image runs still
    # require a full SHA from build metadata.
    return legacy.strip() if isinstance(legacy, str) and legacy.strip() else None
