import base64
import hashlib
import json
import subprocess
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.agent_firewall.connector import OpenSSHSystemdConnector
from app.agent_firewall.targets import SystemdTarget
from scripts.igor_agent_firewall import canonical_json


def _target(key=None):
    key = key or Ed25519PrivateKey.generate()
    public_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_sha = hashlib.sha256(public_raw).hexdigest()
    target = SystemdTarget(
        target_id="staging-api", environment="staging",
        host="staging.example.internal", port=22, user="ola-gateway",
        host_fingerprint="SHA256:" + "A" * 43,
        known_hosts_file="/etc/ola-firewall/known_hosts",
        identity_file="/etc/ola-firewall/id_ed25519",
        identity_public_key_sha256="a" * 64,
        receipt_public_key_raw_b64=base64.b64encode(public_raw).decode("ascii"),
        receipt_public_key_sha256=public_sha,
        receipt_signer_key_id="target-receipt-v1",
        allowed_units=("ola-api.service",), critical=False,
        connect_timeout_s=5, execution_timeout_s=30, config_digest="b" * 64,
    )
    return target, key


def _signed_response(key, request):
    receipt = {
        "schema": "ola.systemd-exec.receipt.v1",
        "request_id": request["request_id"],
        "action_digest": request["action_digest"],
        "operation": "systemd.restart",
        "unit": request["unit"],
        "status": "COMPLETED",
        "reason_code": "SYSTEMD_ACTIVE",
        "started_at": 100, "finished_at": 101,
        "systemctl_exit_code": 0, "active_after": True,
        "signer_key_id": "target-receipt-v1",
    }
    signature = key.sign(canonical_json(receipt).encode("utf-8"))
    public_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "receipt": receipt,
        "signature": {
            "algorithm": "Ed25519", "key_id": "target-receipt-v1",
            "public_key_sha256": hashlib.sha256(public_raw).hexdigest(),
            "value_b64": base64.b64encode(signature).decode("ascii"),
        },
    }


def test_connector_uses_fixed_remote_command_and_signed_receipt():
    target, key = _target()
    captured = {}
    request_id = str(uuid.uuid4())
    digest = "c" * 64

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        request = json.loads(kwargs["input"].decode("utf-8"))
        response = _signed_response(key, request)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(response).encode(), stderr=None)

    result = OpenSSHSystemdConnector(runner=runner).execute(
        target, request_id=request_id, action_digest=digest, unit="ola-api.service"
    )

    assert result.status == "COMPLETED"
    assert result.receipt["action_digest"] == digest
    assert captured["kwargs"]["shell"] is False
    assert captured["command"][-1] == "/usr/bin/sudo -n /usr/local/libexec/ola-systemd-exec"
    assert "ola-api.service" not in captured["command"]
    assert json.loads(captured["kwargs"]["input"])["unit"] == "ola-api.service"


def test_connector_rejects_shell_injection_without_opening_ssh():
    target, _ = _target()
    calls = []
    result = OpenSSHSystemdConnector(runner=lambda *a, **k: calls.append((a, k))).execute(
        target, request_id=str(uuid.uuid4()), action_digest="c" * 64,
        unit="ola-api.service; rm -rf /",
    )

    assert result.status == "BLOCKED"
    assert result.reason_code == "UNIT_NOT_ALLOWLISTED"
    assert calls == []


def test_connector_rejects_receipt_signed_by_wrong_key():
    target, _trusted = _target()
    wrong = Ed25519PrivateKey.generate()

    def runner(command, **kwargs):
        request = json.loads(kwargs["input"].decode("utf-8"))
        response = _signed_response(wrong, request)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(response).encode(), stderr=None)

    result = OpenSSHSystemdConnector(runner=runner).execute(
        target, request_id=str(uuid.uuid4()), action_digest="c" * 64,
        unit="ola-api.service",
    )
    assert result.status == "UNKNOWN"
    assert result.reason_code == "REMOTE_RECEIPT_INVALID"


def test_ssh_timeout_is_unknown_and_not_retried():
    target, _ = _target()
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    result = OpenSSHSystemdConnector(runner=runner).execute(
        target, request_id=str(uuid.uuid4()), action_digest="c" * 64,
        unit="ola-api.service",
    )
    assert result.status == "UNKNOWN"
    assert result.reason_code == "SSH_TIMEOUT"
    assert len(calls) == 1
