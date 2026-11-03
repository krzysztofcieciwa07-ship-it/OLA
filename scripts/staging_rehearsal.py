#!/usr/bin/env python3
"""Ephemeral LOCAL Docker staging: actual HTTP, evidence, tamper and restart.

Never exposes a public listener; cleans only its uniquely named CI volume.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/staging/compose.yaml"
PROOF = ROOT / "staging-proof.json"
URL = "http://127.0.0.1:18080"

SEED = """
import json, sqlite3, sys, uuid
from app.api_key_hashing import api_key_fingerprint
p=json.load(sys.stdin)
db=sqlite3.connect('/data/ola.db')
db.execute('INSERT INTO tenants(id,name) VALUES (?,?)',(p['tenant_id'],'synthetic-staging'))
db.execute('INSERT INTO api_keys(id,tenant_id,key_hash) VALUES (?,?,?)',
           (str(uuid.uuid4()),p['tenant_id'],api_key_fingerprint(p['key'])))
db.commit()
db.close()
"""


def run(*args, input_text=None):
    p = subprocess.run(args, cwd=ROOT, text=True, input=input_text,
                       capture_output=True, check=False, timeout=900)
    if p.returncode:
        # Do not include command arguments or stdout/stderr: they could contain keys.
        raise RuntimeError("staging command failed (exit {})".format(p.returncode))
    return p.stdout.strip()


def http(path, payload=None, key=None):
    content = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-API-Key"] = key
    request = urllib.request.Request(
        URL + path, data=content, headers=headers,
        method="POST" if content is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def await_ready(timeout=110):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            code, body = http("/readyz")
            if (code == 200 and body.get("core_status") == "READY"
                    and body.get("system_acceptance") == "NOT_VERIFIED"):
                return
        except (OSError, ValueError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError("local CORE readiness did not become healthy")


def main():
    commit = os.getenv("OLA_RUNTIME_COMMIT", "")
    pepper = os.getenv("OLA_API_KEY_PEPPER", "")
    if not re.fullmatch("[0-9a-f]{40}", commit) or len(pepper.encode()) < 32:
        print(json.dumps({"status": "BLOCKED", "reason": "missing input configuration"}),
              file=sys.stderr)
        return 2
    project = "ola-stage-" + commit[:9] + "-" + str(os.getpid())
    dc = ("docker", "compose", "-p", project, "-f", str(COMPOSE))
    tenant_id = str(uuid.uuid4())
    api_key = secrets.token_urlsafe(36)
    checks = []
    started = time.monotonic()

    try:
        if run("git", "rev-parse", "HEAD") != commit:
            raise RuntimeError("source checkout does not match expected commit")
        checks.append("exact_source_commit")
        run(*dc, "config", "--quiet")
        checks.append("compose_config")
        run(*dc, "up", "-d", "--build")
        await_ready()
        checks.append("core_readyz")
        run(*dc, "exec", "-T", "ola", "python", "-c", SEED,
            input_text=json.dumps({"tenant_id": tenant_id, "key": api_key}))
        if http("/audit", {"task": "synthetic staging"})[0] != 401:
            raise RuntimeError("unauthenticated request was not rejected")
        if http("/audit", {"task": "synthetic staging"}, key="wrong-key")[0] != 401:
            raise RuntimeError("invalid API key was not rejected")
        checks.append("auth_fail_closed_401")
        code, response = http(
            "/audit", {"task": "synthetic fault and recovery",
                       "scenario": "fault_then_recovery"}, key=api_key,
        )
        if (code != 200 or response.get("status") != "VERIFIED"
                or response.get("evidence_count") != 5):
            raise RuntimeError("synthetic HTTP audit did not emit five evidence records")
        checks.append("audit_http_200")
        verifier = (*dc, "exec", "-T", "ola", "python",
                    "scripts/staging_verify.py", "--tenant-id", tenant_id,
                    "--expected-count", "5")
        before = json.loads(run(*verifier, "--tamper-check"))
        if before.get("status") != "VERIFIED" or not before.get("tamper_blocked"):
            raise RuntimeError("negative append-only test was not verified")
        checks.extend(["independent_v2_chain", "tamper_rejected"])
        run(*dc, "restart", "ola")
        await_ready()
        after = json.loads(run(*verifier))
        if after.get("chain_root") != before.get("chain_root"):
            raise RuntimeError("V2 chain root changed across container restart")
        checks.append("restart_persists_evidence")
        for _ in range(12):
            status, body = http("/readyz")
            if status != 200 or body.get("core_status") != "READY":
                raise RuntimeError("readyz not stable for 12-second observation")
            time.sleep(1)
        checks.append("health_stable_12s")
        proof = {
            "schema": "ola.local-staging-rehearsal.v1",
            "status": "PASS",
            "environment": "LOCAL_CI_ONLY",
            "publicly_deployed": False,
            "system_acceptance": "NOT_VERIFIED",
            "commit": commit,
            "evidence_records": 5,
            "tenant_id": tenant_id,
            "chain_root": after["chain_root"],
            "checks": checks,
            "duration_seconds": round(time.monotonic() - started, 2),
        }
        PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
        print(json.dumps({
            "status": "PASS", "checks": len(checks), "proof": PROOF.name,
            "proof_sha256": hashlib.sha256(PROOF.read_bytes()).hexdigest(),
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc), "checks": checks}),
              file=sys.stderr)
        return 1
    finally:
        subprocess.run((*dc, "down", "--volumes", "--remove-orphans"), cwd=ROOT,
                       capture_output=True, text=True, check=False, timeout=120)


if __name__ == "__main__":
    raise SystemExit(main())
