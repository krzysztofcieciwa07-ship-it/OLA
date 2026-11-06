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


def await_ready(expected_commit, timeout=110):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            code, body = http("/readyz")
            if (code == 200 and body.get("core_status") == "READY"
                    and body.get("system_acceptance") == "NOT_VERIFIED"
                    and body.get("source_commit") == expected_commit):
                return
        except (OSError, ValueError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError("local CORE readiness did not become healthy")

BACKUP_RESTORE = r"""
import json, os, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/app/scripts")
from staging_verify import verify_chain

tenant = os.environ["STAGING_TENANT_ID"]
with tempfile.TemporaryDirectory(prefix="ola-staging-backup-") as directory:
    snapshot_path = str(Path(directory) / "snapshot.sqlite3")
    restored_path = str(Path(directory) / "restored.sqlite3")
    source = sqlite3.connect("/data/ola.db")
    snapshot = sqlite3.connect(snapshot_path)
    try:
        source.backup(snapshot)
    finally:
        source.close()
        snapshot.close()
    snapshot = sqlite3.connect(snapshot_path)
    restored = sqlite3.connect(":memory:")
    try:
        snapshot.backup(restored)
        integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
        count = restored.execute(
            "SELECT COUNT(*) FROM evidence_records WHERE tenant_id=?", (tenant,)
        ).fetchone()[0]
        recovered = sqlite3.connect(restored_path)
        restored.backup(recovered)
        recovered.close()
    finally:
        snapshot.close()
        restored.close()
    verified = verify_chain(restored_path, tenant, expected_count=5)
    if integrity != "ok" or count != 5 or verified.get("status") != "VERIFIED":
        raise RuntimeError("independent SQLite restore verification failed")
print(json.dumps({
    "snapshot_integrity_ok": True,
    "restored_chain_verified": True,
    "restored_records": 5,
    "restored_chain_root": verified["chain_root"],
}, sort_keys=True))
"""


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
    proof = None
    error = None
    PROOF.unlink(missing_ok=True)

    try:
        if run("git", "rev-parse", "HEAD") != commit:
            raise RuntimeError("source checkout does not match expected commit")
        dirty = run(
            "git", "status", "--porcelain", "--untracked-files=all", "--",
            "Dockerfile", ".dockerignore", "requirements.txt", "app", "scripts",
            "tests", "web", "deploy/staging",
        )
        if dirty:
            raise RuntimeError("dirty build inputs cannot be attested")
        checks.append("exact_source_commit")
        run(*dc, "config", "--quiet")
        checks.append("compose_config")
        run(*dc, "up", "-d", "--build")
        image = "ola-staging:" + commit
        image_revision = run(
            "docker", "image", "inspect", "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}', image,
        )
        if image_revision != commit:
            raise RuntimeError("staging image revision label does not match source SHA")
        checks.append("image_revision_matches")
        await_ready(expected_commit=commit)
        checks.append("core_readyz_source_bound")
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
        await_ready(expected_commit=commit)
        after = json.loads(run(*verifier))
        if after.get("chain_root") != before.get("chain_root"):
            raise RuntimeError("V2 chain root changed across container restart")
        checks.append("restart_persists_evidence")
        backup = json.loads(run(
            *dc, "exec", "-T", "-e", "STAGING_TENANT_ID=" + tenant_id,
            "ola", "python", "-", input_text=BACKUP_RESTORE,
        ))
        if (backup.get("snapshot_integrity_ok") is not True
                or backup.get("restored_chain_verified") is not True
                or backup.get("restored_records") != 5
                or backup.get("restored_chain_root") != after.get("chain_root")):
            raise RuntimeError("SQLite backup/restore did not reproduce the verified chain")
        checks.append("sqlite_backup_restore_verified")
        for _ in range(12):
            status, body = http("/readyz")
            if (status != 200 or body.get("core_status") != "READY"
                    or body.get("source_commit") != commit):
                raise RuntimeError("source-bound readyz not stable for 12-second observation")
            time.sleep(1)
        checks.append("health_stable_12s")
        proof = {
            "schema": "ola.local-staging-rehearsal.v1",
            "status": "PASS",
            "environment": "LOCAL_CI_ONLY",
            "publicly_deployed": False,
            "system_acceptance": "NOT_VERIFIED",
            "commit": commit,
            "image_revision": image_revision,
            "source_identity_verified": True,
            "evidence_records": 5,
            "tenant_id": tenant_id,
            "chain_root": after["chain_root"],
            "checks": checks,
            "backup_restore": backup,
            "duration_seconds": round(time.monotonic() - started, 2),
        }
        # Only finalize a PASS receipt AFTER Docker teardown has succeeded.
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
    finally:
        try:
            cleanup = subprocess.run(
                (*dc, "down", "--volumes", "--remove-orphans"), cwd=ROOT,
                capture_output=True, text=True, check=False, timeout=120,
            )
            if cleanup.returncode != 0:
                error = "Docker cleanup failed; resources may remain active"
        except (OSError, subprocess.TimeoutExpired):
            error = "Docker cleanup could not be verified"
    if error is not None:
        PROOF.unlink(missing_ok=True)
        print(json.dumps({"status": "BLOCKED", "error": error, "checks": checks}),
              file=sys.stderr)
        return 1
    if proof is None:
        print(json.dumps({"status": "BLOCKED", "error": "missing proof"}), file=sys.stderr)
        return 1
    PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": "PASS", "checks": len(checks), "proof": PROOF.name,
        "proof_sha256": hashlib.sha256(PROOF.read_bytes()).hexdigest(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
