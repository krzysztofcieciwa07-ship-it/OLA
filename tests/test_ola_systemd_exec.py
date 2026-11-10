import base64
import json
import subprocess
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.ola_systemd_exec import process_request
from scripts.igor_agent_firewall import canonical_json


def _request(*, request_id=None, digest="a" * 64, unit="ola-api.service"):
    return {
        "schema": "ola.systemd-exec.request.v1",
        "request_id": request_id or str(uuid.uuid4()),
        "action_digest": digest,
        "operation": "systemd.restart",
        "unit": unit,
    }


def _verify(response, key):
    receipt = response["receipt"]
    signature = base64.b64decode(response["signature"]["value_b64"])
    key.public_key().verify(signature, canonical_json(receipt).encode("utf-8"))
    return receipt


def test_remote_helper_runs_only_fixed_systemctl_arguments_and_signs_receipt(tmp_path):
    key = Ed25519PrivateKey.generate()
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    response = process_request(
        (canonical_json(_request()) + "\n").encode(),
        allowed_units={"ola-api.service"},
        state_db_path=tmp_path / "state" / "requests.sqlite3",
        private_key=key,
        signer_key_id="target-receipt-v1",
        runner=runner,
        now=lambda: 100,
    )

    receipt = _verify(response, key)
    assert receipt["status"] == "COMPLETED"
    assert receipt["reason_code"] == "SYSTEMD_ACTIVE"
    assert len(calls) == 2
    assert calls[0][0] == ["/usr/bin/systemctl", "restart", "ola-api.service"]
    assert calls[1][0] == ["/usr/bin/systemctl", "is-active", "--quiet", "ola-api.service"]
    assert all(kwargs["shell"] is False for _, kwargs in calls)


def test_remote_helper_replay_returns_original_receipt_without_second_restart(tmp_path):
    key = Ed25519PrivateKey.generate()
    calls = []
    request = _request()

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    kwargs = {
        "allowed_units": {"ola-api.service"},
        "state_db_path": tmp_path / "state" / "requests.sqlite3",
        "private_key": key,
        "signer_key_id": "target-receipt-v1",
        "runner": runner,
        "now": lambda: 100,
    }
    raw = (canonical_json(request) + "\n").encode()
    first = process_request(raw, **kwargs)
    second = process_request(raw, **kwargs)

    assert first == second
    assert _verify(second, key)["status"] == "COMPLETED"
    assert len(calls) == 2


def test_remote_helper_blocks_same_request_id_with_different_action_digest(tmp_path):
    key = Ed25519PrivateKey.generate()
    calls = []
    request_id = str(uuid.uuid4())

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    common = {
        "allowed_units": {"ola-api.service"},
        "state_db_path": tmp_path / "state" / "requests.sqlite3",
        "private_key": key,
        "signer_key_id": "target-receipt-v1",
        "runner": runner,
    }
    process_request((canonical_json(_request(request_id=request_id))+"\n").encode(), **common)
    replay = process_request(
        (canonical_json(_request(request_id=request_id, digest="b" * 64))+"\n").encode(),
        **common,
    )

    assert _verify(replay, key)["status"] == "BLOCKED"
    assert _verify(replay, key)["reason_code"] == "REQUEST_ID_REPLAY_MISMATCH"
    assert len(calls) == 2


def test_remote_helper_timeout_is_unknown_and_never_retries(tmp_path):
    key = Ed25519PrivateKey.generate()
    calls = []
    request = _request()

    def runner(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    kwargs = {
        "allowed_units": {"ola-api.service"},
        "state_db_path": tmp_path / "state" / "requests.sqlite3",
        "private_key": key,
        "signer_key_id": "target-receipt-v1",
        "runner": runner,
    }
    raw = (canonical_json(request) + "\n").encode()
    first = process_request(raw, **kwargs)
    second = process_request(raw, **kwargs)

    assert _verify(first, key)["status"] == "UNKNOWN"
    assert first == second
    assert len(calls) == 1


def test_remote_helper_rejects_unallowlisted_or_injected_unit_before_systemctl(tmp_path):
    key = Ed25519PrivateKey.generate()
    calls = []
    request = _request(unit="ola-api.service;rm -rf /")

    with pytest.raises(ValueError):
        process_request(
            (canonical_json(request) + "\n").encode(),
            allowed_units={"ola-api.service"},
            state_db_path=tmp_path / "state" / "requests.sqlite3",
            private_key=key,
            signer_key_id="target-receipt-v1",
            runner=lambda *a, **k: calls.append((a, k)),
        )
    assert calls == []


def test_remote_helper_rejects_duplicate_json_keys(tmp_path):
    key = Ed25519PrivateKey.generate()
    raw = (
        '{"schema":"ola.systemd-exec.request.v1","request_id":"' + str(uuid.uuid4()) +
        '","action_digest":"' + "a"*64 +
        '","operation":"systemd.restart","unit":"ola-api.service","unit":"evil.service"}'
    ).encode()
    with pytest.raises(ValueError):
        process_request(
            raw,
            allowed_units={"ola-api.service"},
            state_db_path=tmp_path / "state" / "requests.sqlite3",
            private_key=key,
            signer_key_id="target-receipt-v1",
        )
