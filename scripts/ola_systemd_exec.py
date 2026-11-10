#!/usr/bin/env python3
"""Root-owned, idempotent systemd restart helper invoked by forced SSH command.

No shell strings or user-supplied executable paths are accepted. Install this
file root:root 0755, the allowlist root:root 0644, and signing key root:root 0600.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ALLOWED_UNITS_PATH = Path("/etc/ola-agent-firewall/allowed-units.json")
PRIVATE_KEY_PATH = Path("/etc/ola-agent-firewall/receipt-ed25519.pem")
STATE_DB_PATH = Path("/var/lib/ola-agent-firewall/requests.sqlite3")
MAX_INPUT_BYTES = 4096
_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,126}\.service$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_KEYS = {"schema", "request_id", "action_digest", "operation", "unit"}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON constant")


def _check_depth(value, depth=0):
    if depth > 16:
        raise ValueError("request nesting limit exceeded")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("request object keys must be strings")
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def _parse_request(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("request_size_invalid")
    request = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=_reject_constant,
    )
    _check_depth(request)
    if not isinstance(request, dict) or set(request) != _REQUEST_KEYS:
        raise ValueError("request_schema_invalid")
    if request["schema"] != "ola.systemd-exec.request.v1":
        raise ValueError("request_schema_invalid")
    uuid.UUID(request["request_id"])
    if not isinstance(request["action_digest"], str) or not _HEX64_RE.fullmatch(request["action_digest"]):
        raise ValueError("action_digest_invalid")
    if request["operation"] != "systemd.restart":
        raise ValueError("operation_not_allowlisted")
    if not isinstance(request["unit"], str) or not _UNIT_RE.fullmatch(request["unit"]):
        raise ValueError("unit_invalid")
    return request


def _sign_receipt(receipt: dict, private_key: Ed25519PrivateKey, signer_key_id: str) -> dict:
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_sha = hashlib.sha256(public_raw).hexdigest()
    signature = private_key.sign(_canonical(receipt).encode("utf-8"))
    return {
        "receipt": receipt,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": signer_key_id,
            "public_key_sha256": public_sha,
            "value_b64": base64.b64encode(signature).decode("ascii"),
        },
    }


def _make_receipt(request, *, status, reason_code, started_at, finished_at,
                  exit_code=None, active_after=None, signer_key_id):
    return {
        "schema": "ola.systemd-exec.receipt.v1",
        "request_id": request["request_id"],
        "action_digest": request["action_digest"],
        "operation": request["operation"],
        "unit": request["unit"],
        "status": status,
        "reason_code": reason_code,
        "started_at": int(started_at),
        "finished_at": int(finished_at),
        "systemctl_exit_code": exit_code,
        "active_after": active_after,
        "signer_key_id": signer_key_id,
    }


def _open_state_db(path: Path):
    if path.is_symlink():
        raise PermissionError("state database must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        parent_info = path.parent.stat()
        if parent_info.st_uid != os.geteuid() or stat.S_IMODE(parent_info.st_mode) & 0o077:
            raise PermissionError("state directory must be owned by executor and mode 0700")
        if path.exists():
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise PermissionError("state database must be owned by executor and mode 0600")
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            request_id TEXT PRIMARY KEY,
            action_digest TEXT NOT NULL,
            unit TEXT NOT NULL,
            status TEXT NOT NULL,
            response_json TEXT,
            created_at INTEGER NOT NULL
        )
    """)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return connection


def process_request(
    raw: bytes,
    *,
    allowed_units: set[str],
    state_db_path: str | Path,
    private_key: Ed25519PrivateKey,
    signer_key_id: str,
    runner=subprocess.run,
    now=time.time,
) -> dict:
    request = _parse_request(raw)
    if (
        not isinstance(allowed_units, (set, frozenset))
        or any(not isinstance(item, str) or not _UNIT_RE.fullmatch(item) for item in allowed_units)
    ):
        raise ValueError("target allowlist is invalid")
    started_at = int(now())
    if request["unit"] not in allowed_units:
        receipt = _make_receipt(
            request, status="BLOCKED", reason_code="UNIT_NOT_ALLOWLISTED",
            started_at=started_at, finished_at=int(now()), signer_key_id=signer_key_id,
        )
        return _sign_receipt(receipt, private_key, signer_key_id)

    connection = _open_state_db(Path(state_db_path))
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT action_digest, status, response_json FROM executions WHERE request_id=?",
            (request["request_id"],),
        ).fetchone()
        if existing:
            stored_digest, stored_status, stored_response = existing
            connection.execute("COMMIT")
            if stored_digest != request["action_digest"]:
                receipt = _make_receipt(
                    request, status="BLOCKED", reason_code="REQUEST_ID_REPLAY_MISMATCH",
                    started_at=started_at, finished_at=int(now()), signer_key_id=signer_key_id,
                )
                return _sign_receipt(receipt, private_key, signer_key_id)
            if stored_response and stored_status in {"COMPLETED", "FAILED", "UNKNOWN"}:
                return json.loads(stored_response)
            receipt = _make_receipt(
                request, status="UNKNOWN", reason_code="REQUEST_ALREADY_IN_PROGRESS",
                started_at=started_at, finished_at=int(now()), signer_key_id=signer_key_id,
            )
            return _sign_receipt(receipt, private_key, signer_key_id)

        connection.execute(
            "INSERT INTO executions(request_id, action_digest, unit, status, created_at) "
            "VALUES(?, ?, ?, 'IN_PROGRESS', ?)",
            (request["request_id"], request["action_digest"], request["unit"], started_at),
        )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise

    exit_code = None
    active_after = None
    try:
        restart = runner(
            ["/usr/bin/systemctl", "restart", request["unit"]],
            capture_output=True, text=True, timeout=25, check=False, shell=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        exit_code = restart.returncode
        if exit_code != 0:
            status, reason = "FAILED", "SYSTEMD_RESTART_FAILED"
        else:
            active = runner(
                ["/usr/bin/systemctl", "is-active", "--quiet", request["unit"]],
                capture_output=True, text=True, timeout=10, check=False, shell=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
            active_after = active.returncode == 0
            if active_after:
                status, reason = "COMPLETED", "SYSTEMD_ACTIVE"
            else:
                status, reason = "FAILED", "SYSTEMD_NOT_ACTIVE"
    except subprocess.TimeoutExpired:
        status, reason = "UNKNOWN", "SYSTEMD_TIMEOUT"
    except Exception:
        status, reason = "UNKNOWN", "SYSTEMD_EXECUTION_ERROR"

    receipt = _make_receipt(
        request, status=status, reason_code=reason,
        started_at=started_at, finished_at=int(now()),
        exit_code=exit_code, active_after=active_after,
        signer_key_id=signer_key_id,
    )
    response = _sign_receipt(receipt, private_key, signer_key_id)
    response_json = _canonical(response)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "UPDATE executions SET status=?, response_json=? WHERE request_id=? AND action_digest=?",
            (status, response_json, request["request_id"], request["action_digest"]),
        )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    return response


def _load_allowed_units(path=ALLOWED_UNITS_PATH):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise PermissionError("allowed-units file must be root-owned and not group/world writable")
    raw = path.read_bytes()
    if not raw or len(raw) > 16 * 1024:
        raise ValueError("allowed-units file size invalid")
    units = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    _check_depth(units)
    if not isinstance(units, list) or not units:
        raise ValueError("allowed-units file must be a non-empty array")
    if any(not isinstance(unit, str) or not _UNIT_RE.fullmatch(unit) for unit in units):
        raise ValueError("allowed-units file contains an invalid unit")
    return set(units)


def _load_private_key(path=PRIVATE_KEY_PATH):
    path = Path(path)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode) or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise PermissionError("receipt private key must be root-owned mode 0600")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("receipt private key must be Ed25519")
    return key


def main():
    if os.name == "posix" and os.geteuid() != 0:
        raise SystemExit(77)
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    try:
        response = process_request(
            raw,
            allowed_units=_load_allowed_units(),
            state_db_path=STATE_DB_PATH,
            private_key=_load_private_key(),
            signer_key_id="ola-systemd-target-receipt-v1",
        )
    except Exception:
        raise SystemExit(78)
    sys.stdout.write(_canonical(response) + "\n")


if __name__ == "__main__":
    main()
