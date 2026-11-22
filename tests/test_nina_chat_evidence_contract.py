"""NINA chat is completion-only and every terminal decision is tenant-evidenced."""
import hashlib
import json
import uuid
from datetime import datetime

import httpx
from fastapi.testclient import TestClient
import pytest

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.evidence_v4 import V4_META_KEY
from app.igor_evidence_verifier import evidence_version, trusted_record, verify_chain
from app.main import app, read_tenant_evidence
from app.models import ApiKey, Tenant


def _seed_tenant():
    tenant_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="nina-chat-evidence-contract"))
        db.commit()
        db.add(ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=api_key_fingerprint(f"product-key-{tenant_id}"),
        ))
        db.commit()
    return tenant_id


def _chat(tenant_id, message="private customer prompt"):
    return TestClient(app).post(
        "/chat",
        headers={"X-API-Key": f"product-key-{tenant_id}"},
        json={"messages": [{"role": "user", "content": message}]},
    )


def _one_evidenced_record(tenant_id, result, expected_type):
    rows = read_tenant_evidence(tenant_id)
    assert verify_chain(rows) == (True, "ok")
    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == tenant_id
    assert row["id"] == result["evidence_id"]
    assert row["record_type"] == expected_type
    assert evidence_version(row) == 4
    metadata = json.loads(row["payload_json"])[V4_META_KEY]
    assert metadata["record_type"] == expected_type
    assert metadata["producer"] == "ola_runtime"
    if expected_type == "decision.chat":
        assert trusted_record(row)
    return json.loads(row["payload_json"])


def row_json(payload):
    return json.dumps(payload, sort_keys=True)


class Response:
    def __init__(self, status_code=200, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("provider status", request=request, response=response)

    def json(self):
        return self.payload


def test_missing_provider_key_records_tenant_scoped_trusted_block(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "OPENAI_API_KEY is not configured"

    payload = _one_evidenced_record(tenant_id, result, "decision.chat")
    assert payload["decision"] == "BLOCK"
    assert payload["reason"] == result["reason"]
    assert payload["message_count"] == 1
    assert datetime.fromisoformat(payload["observed_at_utc"]).utcoffset().total_seconds() == 0
    assert "private customer prompt" not in row_json(payload)
    assert f"product-key-{tenant_id}" not in row_json(payload)


def test_provider_transport_failure_records_block_before_returning(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")

    def failed_provider(url, **kwargs):
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("simulated provider outage", request=request)

    monkeypatch.setattr("app.chat_runtime.httpx.post", failed_provider)
    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "LLM request failed: ConnectError"

    payload = _one_evidenced_record(tenant_id, result, "decision.chat")
    assert payload["decision"] == "BLOCK"
    assert "test-only-placeholder" not in row_json(payload)


def test_successful_chat_is_completion_not_execution_verification(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OLA_LLM_ALLOWED_HOSTS", raising=False)
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(payload={"output_text": "hello from provider"})

    monkeypatch.setattr("app.chat_runtime.httpx.post", fake_post)
    response = _chat(tenant_id, "hello")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "COMPLETED_UNVERIFIED"
    assert result["verified"] is False
    assert result["message"] == "hello from provider"
    assert result["model"]

    assert calls[0][0] == "https://api.openai.com/v1/responses"
    assert calls[0][1]["follow_redirects"] is False
    assert calls[0][1]["timeout"] == 45
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-only-placeholder"
    assert calls[0][1]["json"]["input"][-1] == {"role": "user", "content": "hello"}

    payload = _one_evidenced_record(tenant_id, result, "chat.completed")
    assert payload["message_count"] == 1
    assert payload["response_digest"] == hashlib.sha256(
        b"hello from provider"
    ).hexdigest()
    assert datetime.fromisoformat(payload["observed_at_utc"]).utcoffset().total_seconds() == 0
    assert "hello from provider" not in row_json(payload)
    assert "hello" not in row_json(payload)
    assert "test-only-placeholder" not in row_json(payload)


def test_chat_blocks_redirect_without_following_it(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(status_code=307, headers={"Location": "https://evil.example/steal"})

    monkeypatch.setattr("app.chat_runtime.httpx.post", fake_post)
    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "LLM request redirected"
    assert calls[0][1]["follow_redirects"] is False

    payload = _one_evidenced_record(tenant_id, result, "decision.chat")
    assert payload["decision"] == "BLOCK"
    assert "evil.example" not in row_json(payload)
    assert "test-only-placeholder" not in row_json(payload)


def test_chat_blocks_unallowlisted_endpoint_without_network_call(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://evil.example/v1")
    monkeypatch.setenv("OLA_LLM_ALLOWED_HOSTS", "api.openai.com")

    def unexpected_post(*args, **kwargs):
        raise AssertionError("network call must not occur")

    monkeypatch.setattr("app.chat_runtime.httpx.post", unexpected_post)
    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "OPENAI_BASE_URL is not an approved HTTPS LLM endpoint"

    payload = _one_evidenced_record(tenant_id, result, "decision.chat")
    assert payload["decision"] == "BLOCK"


def test_chat_host_only_allowlist_rejects_nondefault_port(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com:8443/v1")
    monkeypatch.setenv("OLA_LLM_ALLOWED_HOSTS", "api.openai.com")

    def unexpected_post(*args, **kwargs):
        raise AssertionError("network call must not occur")

    monkeypatch.setattr("app.chat_runtime.httpx.post", unexpected_post)
    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "OPENAI_BASE_URL is not an approved HTTPS LLM endpoint"


def test_chat_explicit_host_port_allowlist_and_redirect_disabled(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com:8443/v1")
    monkeypatch.setenv("OLA_LLM_ALLOWED_HOSTS", "api.openai.com:8443")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(payload={"output_text": "port allowlisted"})

    monkeypatch.setattr("app.chat_runtime.httpx.post", fake_post)
    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "COMPLETED_UNVERIFIED"
    assert result["verified"] is False
    assert result["message"] == "port allowlisted"
    assert calls[0][0] == "https://api.openai.com:8443/v1/responses"
    assert calls[0][1]["follow_redirects"] is False


def test_chat_fails_closed_when_evidence_writer_is_unavailable(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def broken_append(*args, **kwargs):
        raise RuntimeError("simulated evidence writer outage")

    monkeypatch.setattr("app.main.append_record", broken_append)
    with pytest.raises(RuntimeError, match="simulated evidence writer outage"):
        _chat(tenant_id)
