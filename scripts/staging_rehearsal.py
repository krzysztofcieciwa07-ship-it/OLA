#!/usr/bin/env python3
"""Launch a real Docker Compose OLA instance, audit it, restart, then verify.

No public listener; no user data; no secrets in the JSON receipt. CI cleanup
removes the ephemeral volume only after checking durability across restart.
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
COMPOSE = ROOT / "deploy" / "staging" / "compose.yaml"
PROOF = ROOT / "staging-proof.json"
URL = "http://127.0.0.1:18080"
SEED = r'''
import json, sqlite3, sys, uuid
from app.api_key_hashing import api_key_fingerprint
input_data = json.load(sys.stdin)
conn = sqlite3.connect('/data/ola.db')
conn.execute('INSERT INTO tenants(id,name) VALUES(?,?)', (input_data['tenant_id'], 'staging-ci-synthetic'))
conn.execute('INSERT INTO api_keys(id,tenant_id,key_hash) VALUES(?,?,?)',
             (str(uuid.uuid4()), input_data['tenant_id'], api_key_fingerprint(input_data['key'])))
conn.commit()
conn.close()
'''


def run(*args, input_text=None):
    proc = subprocess.run(args, cwd=ROOT, input=input_text, text=True,
                          capture_output=True, check=False, timeout=270)
    if proc.returncode:
        # Avoid leaking credentials in exceptions or logged shell commands.
        raise RuntimeError(f"command failed: {args[0]} {args[1]} (exit {proc.returncode})")
    return proc.stdout.strip()


def http(path, payload=None, key=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(URL + path, data=body, method="POST" if body else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def await_health(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, data = http("/health")
            if status == 200 and data.get("status") == "ok":
                return
        except (OSError, ValueError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError("local OLA health did not recover within deadline")


def main():
    sha = os.getenv("OLA_RUNTIME_COMMIT", "")
    pepper = os.getenv("OLA_API_KEY_PEPPER", "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha) or len(pepper) < 32:
        print("BLOCKED: missing or invalid SHA/pepper", file=sys.stderr)
        return 2
    project = "ola-stage-" + sha[:10]
    dc = ("docker", "compose", "-p", project, "-f", str(COMPOSE))
    source_sha = run("git", "rev-parse", "HEAD")
    if source_sha != sha:
        print("BLOCKED: checkout does not match expected SHA", file=sys.stderr)
        return 2
    tenant_id = str(uuid.uuid4())
    api_key = secrets.token_urlsafe(36)
    checks = []
    started = time.monotonic()
    try:
        run(*dc, "config", "--quiet")
        checks.append("compose_config")
        run(*dc, "up", "-d", "--build")
        await_health()
        checks.append("container_health")
        run(*dc, "exec", "-T", "ola", "python", "-c", SEED,
            input_text=json.dumps({"tenant_id": tenant_id, "key": api_key}))
        status, _ = http("/audit", {"task": "synthetic staging check"})
        if status != 401:
            raise RuntimeError("missing credentials did not return HTTP 401")
        status, _ = http("/audit", {"task": "synthetic staging check"}, key="wrong-key")
        if status != 401:
            raise RuntimeError("invalid credentials did not return HTTP 401")
        checks.append("auth_fail_closed_401")
        status, response = http("/audit", {"task": "synthetic fault then recovery", "scenario": "fault_then_recovery"}, key=api_key)
        if status != 200 or response.get("status") != "VERIFIED" or response.get("evidence_count") != 5:
            raise RuntimeError("synthetic audit did not emit five VERIFIED evidence records")
        checks.append("audit_http_200")
        verifier = (*dc, "exec", "-T", "ola", "python", "scripts/staging_verify.py",
                    "--tenant-id", tenant_id, "--expected-count", "5")
        receipt_before = json.loads(run(*verifier, "--tamper-check"))
        if receipt_before.get("status") != "VERIFIED" or not receipt_before.get("tamper_blocked"):
            raise RuntimeError("V2 or append-only tamper check failed")
        checks.extend(["independent_v2_chain", "tamper_rejected"])
        run(*dc, "restart", "ola")
        await_health()
        receipt_after = json.loads(run(*verifier))
        if receipt_after.get("chain_root") != receipt_before.get("chain_root"):
            raise RuntimeError("evidence chain changed after container restart")
        checks.append("restart_persists_evidence")
        # Observe a stable health window, not a single successful response.
        for _ in range(12):
            status, data = http("/health")
            if status != 200 or data.get("status") != "ok":
                raise RuntimeError("health unstable over 12-second observation window")
            time.sleep(1)
        checks.append("health_stable_12s")
        proof = {"schema": "ola.local-staging-rehearsal.v1", "status": "PASS",
                 "commit": sha, "environment": "LOCAL_CI_ONLY", "publicly_deployed": False,
                 "tenant_id": tenant_id, "evidence_records": 5,
                 "chain_root": receipt_after["chain_root"], "checks": checks,
                 "duration_seconds": round(time.monotonic()-started, 2)}
        PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n")
        print(json.dumps({"status": "PASS", "checks": len(checks), "proof": PROOF.name,
                          "proof_sha256": hashlib.sha256(PROOF.read_bytes()).hexdigest()}, sort_keys=True))
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "checks": checks}), file=sys.stderr)
        return 1
    finally:
        subprocess.run((*dc, "down", "--volumes", "--remove-orphans"),
                       cwd=ROOT, capture_output=True, text=True, timeout=90, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
