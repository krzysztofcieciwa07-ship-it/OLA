from app.api_key_hashing import api_key_fingerprint
import hashlib
import http.client
import io
import json
import urllib.error
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.hashchain import trusted_record, verify_chain
from app.models import ApiKey, Tenant
from app.main import app, read_tenant_evidence


def _seed_tenant():
    db = SessionLocal()
    tenant = Tenant(id=str(uuid.uuid4()), name="nina-chat-e2e")
    db.add(tenant)
    db.commit()
    db.add(
        ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            key_hash=api_key_fingerprint(f"product-key-{tenant.id}"),
        )
    )
    db.commit()
    tenant_id = tenant.id
    db.close()
    return tenant_id


def test_nina_home_is_served():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "NINA" in response.text


def test_nina_chat_requires_authenticated_tenant():
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 401


def test_nina_chat_route_reaches_runtime(monkeypatch):
    tenant_id = _seed_tenant()

    def fake_chat(received_tenant_id, messages):
        assert received_tenant_id == tenant_id
        assert messages == [{"role": "user", "content": "hello"}]
        return {"status": "VERIFIED", "message": "hello from test"}

    monkeypatch.setattr("app.main.chat", fake_chat)

    client = TestClient(app)
    response = client.post(
        "/chat",
        headers={"X-API-Key": f"product-key-{tenant_id}"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "VERIFIED"
    assert response.json()["message"] == "hello from test"


@pytest.mark.parametrize(
    "failure,expected_reason",
    [
        ("unconfigured", "OPENAI_API_KEY is not configured"),
        ("network", "LLM request failed: URLError"),
        ("connection_reset", "LLM request failed: ConnectionResetError"),
        ("incomplete_read", "LLM request failed: IncompleteRead"),
        ("empty", "LLM returned no output"),
        ("invalid_json", "LLM returned invalid JSON"),
        ("invalid_utf8", "LLM returned invalid JSON"),
        ("invalid_response", "LLM returned invalid response"),
        ("invalid_content", "LLM returned invalid response"),
        ("invalid_output_type", "LLM returned invalid response"),
    ],
)
def test_nina_chat_block_has_trusted_tenant_evidence(monkeypatch, failure, expected_reason):
    tenant_id = _seed_tenant()
    if failure == "unconfigured":
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        def fake_urlopen(*args, **kwargs):
            raise AssertionError("provider must not be called without configuration")
    else:
        monkeypatch.setenv("OPENAI_API_KEY", "placeholder-test-only")

        def fake_urlopen(*args, **kwargs):
            if failure == "network":
                raise urllib.error.URLError("simulated")
            if failure == "connection_reset":
                raise ConnectionResetError("simulated")
            if failure == "incomplete_read":
                raise http.client.IncompleteRead(b"partial")
            body = {
                "empty": b'{"output":[]}',
                "invalid_json": b"not-json",
                "invalid_utf8": b"\xff",
                "invalid_response": b"[]",
                "invalid_content": b'{"output":[{"content":[42]}]}',
                "invalid_output_type": b'{"output":null}',
            }[failure]
            return io.BytesIO(body)

    monkeypatch.setattr("app.chat_runtime.urllib.request.urlopen", fake_urlopen)
    client = TestClient(app)
    response = client.post(
        "/chat",
        headers={"X-API-Key": f"product-key-{tenant_id}"},
        json={"messages": [{"role": "user", "content": "private customer content"}]},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == expected_reason
    rows = read_tenant_evidence(tenant_id)
    assert verify_chain(rows) == (True, "ok")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == result["evidence_id"]
    assert row["record_type"] == "decision.chat"
    assert trusted_record(row)
    payload = json.loads(row["payload_json"])
    assert payload["decision"] == "BLOCK"
    assert payload["reason"] == expected_reason
    assert payload["message_count"] == 1
    assert datetime.fromisoformat(payload["observed_at_utc"]).utcoffset().total_seconds() == 0
    assert "private customer content" not in row["payload_json"]
    assert "placeholder-test-only" not in row["payload_json"]
    assert read_tenant_evidence("another-tenant-id") == []


def test_nina_chat_block_fails_closed_when_evidence_unavailable(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def broken_append(*args, **kwargs):
        raise RuntimeError("simulated audit outage")

    monkeypatch.setattr("app.main.append_record", broken_append)
    client = TestClient(app)
    with pytest.raises(RuntimeError, match="simulated audit outage"):
        client.post(
            "/chat",
            headers={"X-API-Key": f"product-key-{tenant_id}"},
            json={"messages": [{"role": "user", "content": "hello"}]},
        )


@pytest.mark.parametrize("body", [
    b'{"output_text":"hello from provider"}',
    b'{"output":[{"content":[{"type":"output_text","text":"hello from provider"}]}]}',
])
def test_nina_chat_success_keeps_completion_evidence(monkeypatch, body):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-test-only")
    monkeypatch.setattr(
        "app.chat_runtime.urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(body),
    )
    response = TestClient(app).post(
        "/chat",
        headers={"X-API-Key": f"product-key-{tenant_id}"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "VERIFIED"
    assert result["message"] == "hello from provider"
    rows = read_tenant_evidence(tenant_id)
    assert verify_chain(rows) == (True, "ok")
    assert len(rows) == 1
    assert rows[0]["record_type"] == "chat.completed"
    assert rows[0]["id"] == result["evidence_id"]
    assert "hello from provider" not in rows[0]["payload_json"]
