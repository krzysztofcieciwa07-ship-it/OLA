"""Read-only adapter for CLI-Hub catalogue discovery.

This module deliberately exposes search only. It never installs, updates,
uninstalls, launches, or executes a discovered CLI.
"""
import hashlib
import json
import os
import subprocess
import tempfile


MAX_QUERY_LENGTH = 120
MAX_OUTPUT_BYTES = 65536
MAX_ERROR_BYTES = 4096
TIMEOUT_SECONDS = 8


class CliHubError(RuntimeError):
    """A bounded CLI-Hub discovery operation could not be completed."""


def _child_environment():
    # Do not forward API keys, cloud credentials, or the full application
    # environment to a third-party CLI. Keep only runtime essentials.
    allowed = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "APPDATA",
               "LOCALAPPDATA", "TMP", "TEMP")
    env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    env["CLI_HUB_NO_ANALYTICS"] = "1"
    return env


def search_catalog(query):
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("CLI-Hub query must contain 1 to 120 characters")
    query = query.strip()

    # Fixed executable and subcommand; query is one argv item. No shell,
    # interpolation, install command, or user-selected executable is allowed.
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            completed = subprocess.run(
                ["cli-hub", "search", query, "--json"],
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                check=False,
                timeout=TIMEOUT_SECONDS,
                shell=False,
                env=_child_environment(),
            )
        except FileNotFoundError as exc:
            raise CliHubError("cli-hub executable is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise CliHubError("CLI-Hub catalogue search timed out") from exc
        except OSError as exc:
            raise CliHubError("CLI-Hub could not be started") from exc

        stdout_file.seek(0, os.SEEK_END)
        output_size = stdout_file.tell()
        if output_size > MAX_OUTPUT_BYTES:
            raise CliHubError("CLI-Hub output exceeds 65536-byte limit")
        stdout_file.seek(0)
        raw_output = stdout_file.read(MAX_OUTPUT_BYTES + 1)

        stderr_file.seek(0, os.SEEK_END)
        error_size = stderr_file.tell()
        stderr_file.seek(0)
        error_output = stderr_file.read(MAX_ERROR_BYTES).decode("utf-8", errors="replace")

    if completed.returncode != 0:
        raise CliHubError(
            f"CLI-Hub search failed with exit code {completed.returncode}: "
            f"{error_output[:MAX_ERROR_BYTES]}"
        )
    try:
        catalog = json.loads(raw_output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliHubError("CLI-Hub returned invalid JSON") from exc
    if not isinstance(catalog, (dict, list)):
        raise CliHubError("CLI-Hub JSON must be an object or array")

    return {
        "provider": "cli-hub",
        "operation": "search",
        "query": query,
        "catalog": catalog,
        "output_sha256": hashlib.sha256(raw_output).hexdigest(),
        "output_bytes": len(raw_output),
        "exit_code": completed.returncode,
        "stderr_truncated": error_size > MAX_ERROR_BYTES,
    }
