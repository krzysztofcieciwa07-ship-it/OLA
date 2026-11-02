"""AutoGPT v2 is an optional, owner-only, fail-closed external executor."""
import hashlib
import json
import uuid
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app.api_key_hashing import api_key_fingerprint
from app.autogpt_v2 import AutoGPTBridgeError, AutoGPTV2Client
from app.database import SessionLocal
from app.hashchain import trusted_record
from app.models import ApiKey, Tenant
import app.main as main


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self, _max):
        return self.body


class FakeOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def _client(opener, **kwargs):
    return AutoGPTV2Client(
        base_url="https://backend.agpt.co/api/v2", api_key="test-remote-key",
        agent_id="agent-123", input_field="prompt", allowed_hosts=["backend.agpt.co"],
        opener=opener, **kwargs,
    )


def test_real_v2_request_shape_and_completed_is_only_remote_observation():
    opener = FakeOpener([
        FakeResponse(202, {"id": "run-123", "status": "QUEUED"}),
        FakeResponse(200, {"id": "run-123", "status": "COMPLETED", "outputs": {"text": ["ok"]}}),
    ])
    client = _client(opener)
    assert client.start("analyse", idempotency_key="a" * 64) == {
        "run_id": "run-123", "remote_status": "QUEUED",
    }
    assert client.poll("run-123") == {
        "run_id": "run-123", "remote_status": "COMPLETED", "outputs": {"text": ["ok"]},
    }
    post, timeout = opener.calls[0]
    assert timeout == 10
    assert post.full_url == "https://backend.agpt.co/api/v2/library/agents/agent-123/runs"
    assert post.get_method() == "POST"
    assert json.loads(post.data) == {"inputs": {"prompt": "analyse"}}
    assert post.get_header("X-api-key") == "test-remote-key"
    assert post.get_header("Idempotency-key") == "a" * 64
    assert opener.calls[1][0].full_url.endswith("/runs/run-123")


@pytest.mark.parametrize("base,allowed,local", [
    ("http://backend.agpt.co/api/v2", ["backend.agpt.co"], False),
    ("https://internal.invalid/api/v2", ["backend.agpt.co"], False),
    ("https://backend.agpt.co/api/v2?x=1", ["backend.agpt.co"], False),
    ("https://user:pass@backend.agpt.co/api/v2", ["backend.agpt.co"], False),
    ("http://169.254.169.254/api/v2", ["169.254.169.254"], True),
])
def test_untrusted_origin_is_blocked(base, allowed, local):
    with pytest.raises(AutoGPTBridgeError, match="origin"):
        AutoGPTV2Client(base_url=base, api_key="key", agent_id="agent-123",
                        input_field="prompt", allowed_hosts=allowed, allow_local_http=local)


def test_remote_redirect_or_wrong_http_status_does_not_reveal_key():
    for response in (
        HTTPError("https://other.invalid", 302, "redirect", {}, None),
        FakeResponse(200, {"id": "run-123", "status": "COMPLETED"}),
    ):
        with pytest.raises(AutoGPTBridgeError) as exc:
            _client(FakeOpener([response])).start("analyse", idempotency_key="a" * 64)
        assert "test-remote-key" not in str(exc.value)


def _tenant(key):
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="autogpt-bridge-test"))
        db.flush()
        db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                      key_hash=api_key_fingerprint(key)))
        db.commit()
    return tenant_id


class FakeClient:
    starts = []
    polls = []
    agent_id = "agent-123"

    @classmethod
    def from_environment(cls):
        return cls()

    def start(self, task, *, idempotency_key):
        self.starts.append((task, idempotency_key))
        return {"run_id": "run-123", "remote_status": "QUEUED"}

    def poll(self, run_id):
        self.polls.append(run_id)
        return {"run_id": run_id, "remote_status": "COMPLETED", "outputs": {"text": ["done"]}}


def _enable(monkeypatch, tenant_id):
    monkeypatch.setenv("OLA_AUTOGPT_ENABLED", "1")
    monkeypatch.setenv("OLA_AUTOGPT_OWNER_TENANT_ID", tenant_id)
    FakeClient.starts = []
    FakeClient.polls = []
    monkeypatch.setattr(main, "AutoGPTV2Client", FakeClient)


def test_bridge_disabled_or_unauthorized_does_not_dispatch(monkeypatch):
    owner_key = "owner-" + str(uuid.uuid4())
    other_key = "other-" + str(uuid.uuid4())
    owner = _tenant(owner_key)
    _tenant(other_key)
    client = TestClient(main.app)
    request = {"task": "analyse", "operation_id": str(uuid.uuid4())}
    assert client.post("/nina-autogpt", json=request).status_code == 401
    assert client.post("/nina-autogpt", json=request, headers={"X-API-Key": owner_key}).status_code == 503
    _enable(monkeypatch, owner)
    assert client.post("/nina-autogpt", json=request, headers={"X-API-Key": other_key}).status_code == 403
    assert FakeClient.starts == []


def test_owner_run_is_evidence_bound_and_not_verified(monkeypatch):
    key = "owner-" + str(uuid.uuid4())
    tenant = _tenant(key)
    _enable(monkeypatch, tenant)
    operation_id = str(uuid.uuid4())
    request = {"task": "analyse", "operation_id": operation_id}
    headers = {"X-API-Key": key}
    client = TestClient(main.app)
    response = client.post("/nina-autogpt", json=request, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "EXTERNAL_PENDING_UNVERIFIED"
    assert body["igor"] == "UNKNOWN"
    assert body["human_gate"] == "NOT_APPROVED"
    assert body["verified"] is False
    assert body["evidence_ids"] and len(body["evidence_ids"]) == 2
    assert len(FakeClient.starts) == 1
    assert len(FakeClient.starts[0][1]) == 64
    records = main.read_tenant_evidence(tenant)
    assert [row["record_type"] for row in records] == [
        "integration.autogpt.requested", "integration.autogpt.accepted",
    ]
    assert all(trusted_record(row) for row in records)
    assert "analyse" not in " ".join(row["payload_json"] for row in records)
    assert "owner-" not in " ".join(row["payload_json"] for row in records)
    assert client.post("/nina-autogpt", json=request, headers=headers).json()["reused"] is True
    assert len(FakeClient.starts) == 1
    observed = client.get("/nina-autogpt/run-123", headers=headers)
    assert observed.status_code == 200
    assert observed.json()["remote_status"] == "COMPLETED"
    assert observed.json()["verified"] is False
    assert observed.json()["igor"] == "UNKNOWN"
    assert len(FakeClient.polls) == 1


def test_same_operation_with_new_task_is_rejected(monkeypatch):
    key = "owner-" + str(uuid.uuid4())
    tenant = _tenant(key)
    _enable(monkeypatch, tenant)
    client = TestClient(main.app)
    op = str(uuid.uuid4())
    assert client.post("/nina-autogpt", headers={"X-API-Key": key},
                       json={"task": "first", "operation_id": op}).status_code == 200
    assert client.post("/nina-autogpt", headers={"X-API-Key": key},
                       json={"task": "second", "operation_id": op}).status_code == 409
    assert len(FakeClient.starts) == 1


def test_evidence_failure_prevents_remote_dispatch_and_spoofing(monkeypatch):
    key = "owner-" + str(uuid.uuid4())
    tenant = _tenant(key)
    _enable(monkeypatch, tenant)
    client = TestClient(main.app)
    forbidden = client.post("/evidence", headers={"X-API-Key": key}, json={
        "record_type": "integration.autogpt.accepted", "payload": {"run_id": "run-123"},
    })
    assert forbidden.status_code == 403
    monkeypatch.setattr(main, "append_record", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    result = client.post("/nina-autogpt", headers={"X-API-Key": key}, json={
        "task": "analyse", "operation_id": str(uuid.uuid4()),
    })
    assert result.status_code == 503
    assert FakeClient.starts == []


def test_unknown_remote_outcome_is_not_retried(monkeypatch):
    key = "owner-" + str(uuid.uuid4())
    tenant = _tenant(key)
    _enable(monkeypatch, tenant)
    def failed_start(_self, *_args, **_kwargs):
        FakeClient.starts.append("attempted")
        raise AutoGPTBridgeError("network uncertain")
    monkeypatch.setattr(FakeClient, "start", failed_start)
    client = TestClient(main.app)
    data = {"task": "analyse", "operation_id": str(uuid.uuid4())}
    headers = {"X-API-Key": key}
    assert client.post("/nina-autogpt", json=data, headers=headers).status_code == 502
    assert client.post("/nina-autogpt", json=data, headers=headers).status_code == 409
    assert FakeClient.starts == ["attempted"]
    assert client.get("/nina-autogpt/run-other", headers=headers).status_code == 404
