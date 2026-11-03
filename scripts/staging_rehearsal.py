#!/usr/bin/env python3
"""Ephemeral loopback Docker staging acceptance, with real SQLite persistence.

Test ONLY: no public bind, external API keys, production credentials or deployment.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from operator_http_rehearsal import run_operator_http_rehearsal

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/staging/compose.yaml"


def run(command, env, *, timeout=120):
    completed = subprocess.run(
        command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout
    )
    if completed.returncode:
        # Output may include tool debug information, never print secret-bearing
        # environment/config or compose's resolved values.
        raise RuntimeError(f"command failed: {command[0]} (exit {completed.returncode})")
    return completed.stdout


def exec_python(project, env, code, *, tenant=None, variables=None):
    command = ["docker", "compose", "-f", str(COMPOSE), "-p", project, "exec", "-T"]
    if tenant:
        command += ["-e", f"STAGING_TENANT_ID={tenant}"]
    for name, value in (variables or {}).items():
        if not name.startswith("STAGING_") or not isinstance(value, str):
            raise ValueError("test-only environment variable expected")
        command += ["-e", f"{name}={value}"]
    command += ["ola", "python", "-c", code]
    output = run(command, env, timeout=90)
    lines = [line for line in output.splitlines() if line.startswith("STAGING_RECORD=")]
    if len(lines) != 1:
        raise RuntimeError("missing or ambiguous synthetic evidence result")
    return json.loads(lines[0].split("=", 1)[1])


WRITE_RECORD = r"""
import json, os
from app.database import SessionLocal, append_evidence_atomic
from app.models import Tenant
tenant = os.environ["STAGING_TENANT_ID"]
with SessionLocal() as db:
    db.add(Tenant(id=tenant, name="ephemeral staging evidence"))
    db.commit()
out = append_evidence_atomic(tenant, "staging.synthetic_probe", {"synthetic": True})
print("STAGING_RECORD=" + json.dumps(out, sort_keys=True))
"""

VERIFY_RECORD = r"""
import json, os
from sqlalchemy import select
from sqlalchemy.exc import DatabaseError
from app.database import SessionLocal, engine
from app.models import EvidenceRecord
from app.hashchain import verify_chain
tenant = os.environ["STAGING_TENANT_ID"]
with SessionLocal() as db:
    rows = db.scalars(select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant)
                      .order_by(EvidenceRecord.seq.asc())).all()
records = [{"id": row.id, "tenant_id": row.tenant_id, "seq": row.seq,
            "record_type": row.record_type, "payload_json": row.payload_json,
            "prev_hash": row.prev_hash, "record_hash": row.record_hash}
           for row in rows]
ok, reason = verify_chain(records)
if not ok or len(records) != 1:
    raise RuntimeError("chain integrity not verified")
record = records[0]
blocked_update = False
try:
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE evidence_records SET record_type=? WHERE id=?",
                             ("tampered", record["id"]))
except DatabaseError:
    blocked_update = True
if not blocked_update:
    raise RuntimeError("append-only mutation incorrectly allowed")
print("STAGING_RECORD=" + json.dumps({
    "id": record["id"], "tenant_id": record["tenant_id"],
    "seq": record["seq"], "record_hash": record["record_hash"],
    "chain_verified": ok, "mutation_blocked": blocked_update
}, sort_keys=True))
"""


# SQLite online backup into a separate file, then restore into a distinct
# in-memory database. This is not an offsite disaster recovery certification.
BACKUP_RESTORE = r"""
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from app.database import DB_PATH
from app.hashchain import verify_chain

tenant = os.environ["STAGING_TENANT_ID"]
with tempfile.TemporaryDirectory(prefix="ola-staging-backup-") as directory:
    snapshot_path = str(Path(directory) / "evidence-snapshot.sqlite3")
    source = sqlite3.connect(DB_PATH)
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
        result = restored.execute(
            "SELECT id, tenant_id, seq, record_type, payload_json, "
            "prev_hash, record_hash FROM evidence_records "
            "WHERE tenant_id=? ORDER BY seq", (tenant,)
        ).fetchall()
    finally:
        snapshot.close()
        restored.close()

keys = ("id", "tenant_id", "seq", "record_type", "payload_json",
        "prev_hash", "record_hash")
rows = [dict(zip(keys, row)) for row in result]
ok, reason = verify_chain(rows)
if integrity != "ok" or len(rows) != 1 or not ok:
    raise RuntimeError("restored snapshot failed integrity verification")
print("STAGING_RECORD=" + json.dumps({
    "restored_hash": rows[0]["record_hash"],
    "snapshot_chain_verified": True,
    "snapshot_integrity_ok": integrity == "ok",
}, sort_keys=True))
"""


def wait_ready(base, expected_sha, *, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/readyz", timeout=3) as response:
                body = json.load(response)
                if (response.status == 200 and body.get("core_status") == "READY"
                        and body.get("system_acceptance") == "NOT_VERIFIED"
                        and body.get("source_commit") == expected_sha
                        and body.get("failed_checks") == []):
                    return body
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError("readiness missing or wrong source SHA")


def resolve_sha():
    source = os.environ.get("OLA_STAGING_COMMIT") or os.environ.get("GITHUB_SHA")
    if not source:
        source = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    if re.fullmatch(r"[a-fA-F0-9]{40}", source) is None:
        raise RuntimeError("a full 40-char source SHA is required")
    return source.lower()


def main():
    sha = resolve_sha()
    project = "ola-rehearsal-" + uuid.uuid4().hex[:10]
    port = 18080  # only 127.0.0.1; isolated runner recommended
    base = f"http://127.0.0.1:{port}"
    tenant = str(uuid.uuid4())
    env = os.environ.copy()
    env["OLA_STAGING_COMMIT"] = sha
    env["OLA_STAGING_PEPPER"] = secrets.token_hex(32)
    env["OLA_STAGING_PORT"] = str(port)
    cmd = ["docker", "compose", "-f", str(COMPOSE), "-p", project]
    tests = {}
    try:
        run(["docker", "compose", "version"], env, timeout=20)
        run(cmd + ["config", "--quiet"], env)
        run(cmd + ["up", "-d", "--build", "--wait", "--wait-timeout", "160"], env, timeout=480)
        ready = wait_ready(base, sha)
        tests["readyz_core_only"] = ready["scope"] == "local_core_only"
        with urllib.request.urlopen(base + "/health", timeout=5) as r:
            tests["liveness_http_200"] = r.status == 200

        created = exec_python(project, env, WRITE_RECORD, tenant=tenant)
        tests["synthetic_record_written"] = (
            created.get("tenant_id") == tenant
            and created.get("seq") == 0
            and bool(re.fullmatch("[0-9a-f]{64}", created.get("record_hash", "")))
        )
        if not all(tests.values()):
            raise RuntimeError("initial verification failed")

        run(cmd + ["restart", "ola"], env, timeout=90)
        wait_ready(base, sha)
        restored = exec_python(project, env, VERIFY_RECORD, tenant=tenant)
        tests["same_record_after_restart"] = (
            restored.get("id") == created["id"]
            and restored.get("record_hash") == created["record_hash"]
            and restored.get("tenant_id") == tenant
        )
        tests["independent_hashchain_verified"] = restored.get("chain_verified") is True
        tests["append_only_rejects_mutation"] = restored.get("mutation_blocked") is True
        if not all(tests.values()):
            raise RuntimeError("post-restart verification failed")

        recovered = exec_python(project, env, BACKUP_RESTORE, tenant=tenant)
        tests["sqlite_backup_restored_to_independent_database"] = (
            recovered.get("restored_hash") == created["record_hash"]
        )
        tests["restored_database_integrity_ok"] = recovered.get("snapshot_integrity_ok") is True
        tests["restored_evidence_chain_verified"] = recovered.get("snapshot_chain_verified") is True
        if not all(tests.values()):
            raise RuntimeError("independent snapshot restore check failed")

        # Separate real HTTP acceptance on the running container and its
        # persistent SQLite volume. All users and keys are synthetic.
        tests.update(run_operator_http_rehearsal(
            base=base, project=project, env=env, exec_python=exec_python,
        ))
        if not all(tests.values()):
            raise RuntimeError("HTTP operator flow acceptance failed")

        report = {
            "schema": "ola.staging-rehearsal.v1",
            "status": "PASS_LOCAL_STAGING_ONLY",
            "source_commit": sha,
            "synthetic_record_hash": restored["record_hash"],
            "tests": tests,
            "release_gate": "BLOCKED",
            "not_verified": [
                "production data durability", "independent backup restore",
                "MFA", "external signatures", "HTTPS",
                "NOVA multi-user E2EE", "Codex production bridge"
            ],
        }
        output = ROOT / "staging-evidence.json"
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        # Throwaway CI volume: never touch an existing shared or production volume.
        subprocess.run(
            cmd + ["down", "--volumes", "--remove-orphans"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=90, check=False
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STAGING_REHEARSAL_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
