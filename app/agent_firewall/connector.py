"""Inline SSH gateway for the single systemd.restart capability."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import re
import subprocess
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.igor_agent_firewall import canonical_json, strict_json_loads


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_REMOTE_HELPER_COMMAND = "/usr/bin/sudo -n /usr/local/libexec/ola-systemd-exec"
_SSH_BINARY = "/usr/bin/ssh"


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason_code: str
    receipt: dict | None = None
    ssh_return_code: int | None = None


class OpenSSHSystemdConnector:
    """The caller supplies only an inventory target ID and a validated unit."""

    def __init__(self, *, runner=subprocess.run):
        self.runner = runner

    def execute(self, target, *, request_id: str, action_digest: str, unit: str) -> ExecutionResult:
        if not target.allows_unit(unit):
            return ExecutionResult("BLOCKED", "UNIT_NOT_ALLOWLISTED")
        try:
            uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError):
            return ExecutionResult("BLOCKED", "REQUEST_ID_INVALID")
        if not isinstance(action_digest, str) or not _HEX64_RE.fullmatch(action_digest):
            return ExecutionResult("BLOCKED", "ACTION_DIGEST_INVALID")

        payload = (canonical_json({
            "schema": "ola.systemd-exec.request.v1",
            "request_id": request_id,
            "action_digest": action_digest,
            "operation": "systemd.restart",
            "unit": unit,
        }) + "\n").encode("utf-8")
        command = [
            _SSH_BINARY,
            "-F", "/dev/null",
            "-T",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={target.known_hosts_file}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "UpdateHostKeys=no",
            "-o", "VerifyHostKeyDNS=no",
            "-o", f"IdentityFile={target.identity_file}",
            "-o", "IdentitiesOnly=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "ForwardAgent=no",
            "-o", "ClearAllForwardings=yes",
            "-o", "PermitLocalCommand=no",
            "-o", "ProxyCommand=none",
            "-o", "ProxyJump=none",
            "-o", "ControlMaster=no",
            "-o", "RequestTTY=no",
            "-o", f"ConnectTimeout={target.connect_timeout_s}",
            "-o", "ConnectionAttempts=1",
            "-p", str(target.port),
            "--",
            f"{target.user}@{target.host}",
            _REMOTE_HELPER_COMMAND,
        ]
        try:
            completed = self.runner(
                command,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=False,
                timeout=target.execution_timeout_s,
                check=False,
                shell=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult("UNKNOWN", "SSH_TIMEOUT")
        except FileNotFoundError:
            return ExecutionResult("BLOCKED", "SSH_BINARY_UNAVAILABLE")
        except OSError:
            return ExecutionResult("UNKNOWN", "SSH_TRANSPORT_ERROR")

        stdout = completed.stdout or b""
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8", errors="replace")
        if len(stdout) > 16 * 1024:
            return ExecutionResult("UNKNOWN", "REMOTE_RESPONSE_TOO_LARGE", ssh_return_code=completed.returncode)
        try:
            response = strict_json_loads(stdout.decode("utf-8").strip())
            receipt = _verify_receipt(
                response,
                target=target,
                request_id=request_id,
                action_digest=action_digest,
                unit=unit,
            )
        except (ValueError, TypeError, UnicodeError, InvalidSignature, KeyError):
            return ExecutionResult("UNKNOWN", "REMOTE_RECEIPT_INVALID", ssh_return_code=completed.returncode)
        return ExecutionResult(
            status=receipt["status"],
            reason_code=receipt["reason_code"],
            receipt=receipt,
            ssh_return_code=completed.returncode,
        )


def _verify_receipt(response, *, target, request_id, action_digest, unit):
    if not isinstance(response, dict) or set(response) != {"receipt", "signature"}:
        raise ValueError("remote response shape invalid")
    receipt = response["receipt"]
    signature = response["signature"]
    expected_receipt_fields = {
        "schema", "request_id", "action_digest", "operation", "unit",
        "status", "reason_code", "started_at", "finished_at",
        "systemctl_exit_code", "active_after", "signer_key_id",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_receipt_fields:
        raise ValueError("receipt shape invalid")
    if (
        receipt["schema"] != "ola.systemd-exec.receipt.v1"
        or receipt["request_id"] != request_id
        or receipt["action_digest"] != action_digest
        or receipt["operation"] != "systemd.restart"
        or receipt["unit"] != unit
        or receipt["signer_key_id"] != target.receipt_signer_key_id
    ):
        raise ValueError("receipt is not bound to the requested action")
    if receipt["status"] not in {"COMPLETED", "FAILED", "UNKNOWN", "BLOCKED"}:
        raise ValueError("receipt status invalid")
    if not isinstance(receipt["reason_code"], str) or not receipt["reason_code"]:
        raise ValueError("receipt reason invalid")
    if type(receipt["started_at"]) is not int or type(receipt["finished_at"]) is not int:
        raise ValueError("receipt timestamps invalid")
    if receipt["systemctl_exit_code"] is not None and type(receipt["systemctl_exit_code"]) is not int:
        raise ValueError("receipt exit code invalid")
    if receipt["active_after"] is not None and type(receipt["active_after"]) is not bool:
        raise ValueError("receipt active flag invalid")
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm", "key_id", "public_key_sha256", "value_b64"
    }:
        raise ValueError("receipt signature shape invalid")
    if (
        signature["algorithm"] != "Ed25519"
        or signature["key_id"] != target.receipt_signer_key_id
        or signature["public_key_sha256"] != target.receipt_public_key_sha256
    ):
        raise ValueError("receipt signer identity mismatch")
    public_raw = base64.b64decode(target.receipt_public_key_raw_b64, validate=True)
    signature_raw = base64.b64decode(signature["value_b64"], validate=True)
    if len(public_raw) != 32 or len(signature_raw) != 64:
        raise ValueError("receipt signature length invalid")
    Ed25519PublicKey.from_public_bytes(public_raw).verify(
        signature_raw, canonical_json(receipt).encode("utf-8")
    )
    return receipt
