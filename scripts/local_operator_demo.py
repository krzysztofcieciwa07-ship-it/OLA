#!/usr/bin/env python3
"""Start/stop isolated OLA operator demo on local loopback.

Never use for production. Credentials are newly generated test-only strings,
kept in a mode-0600 file under a private HOME directory, not in the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from operator_http_rehearsal import SEED_IDENTITIES
from staging_rehearsal import COMPOSE, ROOT, exec_python, resolve_sha, run


HOME_DIR = Path.home() / ".ola-dios-local"
STATE = HOME_DIR / "operator-demo.json"


def _save_config(info):
    if os.name != "posix":
        raise RuntimeError("Use Linux/macOS or WSL2 with Docker Desktop integration")
    if HOME_DIR.is_symlink() or STATE.is_symlink():
        raise RuntimeError("Unsafe local state symlink")
    HOME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(HOME_DIR, 0o700)
    fd = os.open(STATE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(info, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except Exception:
        STATE.unlink(missing_ok=True)
        raise


def _load_config():
    if os.name != "posix":
        raise RuntimeError("Use Linux/macOS or WSL2 with Docker Desktop integration")
    if HOME_DIR.is_symlink() or STATE.is_symlink():
        raise RuntimeError("Unsafe local state symlink")
    if not STATE.is_file():
        raise RuntimeError("No local demo exists; run 'up' first.")
    if STATE.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe credentials file permissions; refuse to read.")
    data = json.loads(STATE.read_text(encoding="utf-8"))
    if not all(isinstance(data.get(name), str) for name in (
            "project", "pepper", "commit", "requester_key", "reviewer_key")):
        raise RuntimeError("Invalid local demo state")
    return data


def _compose_env(data):
    values = os.environ.copy()
    values["OLA_STAGING_PEPPER"] = data["pepper"]
    values["OLA_STAGING_COMMIT"] = data["commit"]
    values["OLA_STAGING_PORT"] = str(data["port"])
    return values


def _compose_cmd(project):
    return ["docker", "compose", "-f", str(COMPOSE), "-p", project]


def up():
    if STATE.exists():
        raise RuntimeError(
            "Local demo already exists; use status/down, never overwrite it"
        )
    sha = resolve_sha()
    project = "ola-local-operator-" + uuid.uuid4().hex[:10]
    port = int(os.environ.get("OLA_LOCAL_OPERATOR_PORT", "18080"))
    if port < 1024 or port > 65535:
        raise ValueError("Only non-privileged local TCP ports are allowed")

    data = {
        "project": project,
        "port": port,
        "commit": sha,
        "pepper": secrets.token_hex(32),
        "requester_key": secrets.token_urlsafe(36),
        "reviewer_key": secrets.token_urlsafe(36),
        "tenant_id": str(uuid.uuid4()),
        "scope": "SYNTHETIC_LOCAL_ONLY_NOT_PRODUCTION",
    }
    outsider_tenant = str(uuid.uuid4())
    outsider_key = secrets.token_urlsafe(36)
    env = _compose_env(data)
    cmd = _compose_cmd(project)
    try:
        run(["docker", "compose", "version"], env, timeout=20)
        run(cmd + ["config", "--quiet"], env)
        run(cmd + ["up", "-d", "--build", "--wait", "--wait-timeout", "160"],
            env, timeout=480)
        result = exec_python(
            project, env, SEED_IDENTITIES, tenant=data["tenant_id"],
            variables={
                "STAGING_FOREIGN_TENANT_ID": outsider_tenant,
                "STAGING_REQUESTER_TOKEN": data["requester_key"],
                "STAGING_REVIEWER_TOKEN": data["reviewer_key"],
                "STAGING_OUTSIDER_TOKEN": outsider_key,
            },
        )
        if result.get("tenant") != data["tenant_id"]:
            raise RuntimeError("Synthetic identity setup failed")
        _save_config(data)
    except Exception:
        # Remove ONLY the uniquely named project created for this run.
        subprocess.run(
            cmd + ["down", "--volumes", "--remove-orphans"], env=env, cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
            check=False,
        )
        raise
    print("LOCAL_OPERATOR_DEMO: READY_FOR_MANUAL_TEST")
    print("URL: http://127.0.0.1:" + str(port) + "/operator")
    print("TEST CREDENTIALS (private 0600 file): " + str(STATE))
    print("Release decision: BLOCKED — Vantage/NOVA not integrated, not production")
    print("Cleanup: python scripts/local_operator_demo.py down")


def status():
    data = _load_config()
    url = "http://127.0.0.1:" + str(data["port"]) + "/readyz"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = json.load(response)
            healthy = (
                response.status == 200
                and body.get("source_commit") == data["commit"]
                and body.get("core_status") == "READY"
            )
    except (ValueError, OSError, urllib.error.URLError):
        healthy = False
    result = {
        "status": "LOCAL_CORE_READY" if healthy else "BLOCKED",
        "source_commit": data["commit"],
        "url": "http://127.0.0.1:" + str(data["port"]) + "/operator",
        "system_acceptance": "NOT_VERIFIED",
        "credentials_file": str(STATE),
    }
    print(json.dumps(result, indent=2))
    if not healthy:
        raise SystemExit(1)


def down():
    data = _load_config()
    run(_compose_cmd(data["project"]) + [
        "down", "--volumes", "--remove-orphans",
    ], _compose_env(data), timeout=90)
    STATE.unlink()
    print("LOCAL_OPERATOR_DEMO: STOPPED — disposable test volume deleted")


def main():
    parser = argparse.ArgumentParser(
        description="OLA isolated loopback operator demo; NOT for production"
    )
    parser.add_argument("command", choices=("up", "status", "down"))
    args = parser.parse_args()
    try:
        {"up": up, "status": status, "down": down}[args.command]()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("LOCAL_OPERATOR_DEMO: BLOCKED (" + type(exc).__name__ + ")",
              file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
