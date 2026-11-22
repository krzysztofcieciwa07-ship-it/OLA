"""NINA chat is completion-only and every terminal decision is tenant-evidenced."""
import hashlib
import io
import json
import uuid
from datetime import datetime
from urllib.error import URLError

from fastapi.testclient import TestClient
import pytest

from app.api_key_hashing import api_key_fingerprint
from app.database import SessionLocal
from app.igor_evidence_verifier import trusted_record, verify_chain
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


def _one_trusted_record(tenant_id, result, expected_type):
    rows = read_tenant_evidence(tenant_id)
    assert verify_chain(rows) == (True, "ok")
    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == tenant_id
    assert row["id"] == result["evidence_id"]
    assert row["record_type"] == expected_type
    assert trusted_record(row)
    return json.loads(row["payload_json"])


def test_missing_provider_key_records_tenant_scoped_trusted_block(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "OPENAI_API_KEY is not configured"

    payload = _one_trusted_record(tenant_id, result, "decision.chat")
    assert payload["decision"] == "BLOCK"
    assert payload["reason"] == result["reason"]
    assert payload["message_count"] == 1
    assert datetime.fromisoformat(payload["observed_at_utc"]).utcoffset().total_seconds() == 0
    assert "private customer prompt" not in row_json(payload)
    assert f"product-key-{tenant_id}" not in row_json(payload)


def test_provider_transport_failure_records_block_before_returning(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")

    def failed_provider(*args, **kwargs):
        raise URLError("simulated provider outage")

    monkeypatch.setattr("app.chat_runtime.urllib.request.urlopen", failed_provider)
    response = _chat(tenant_id)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "BLOCK"
    assert result["reason"] == "LLM request failed: URLError"

    payload = _one_trusted_record(tenant_id, result, "decision.chat")
    assert payload["decision"] == "BLOCK"
    assert "test-only-placeholder" not in row_json(payload)


def test_successful_chat_is_completion_not_execution_verification(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.setattr(
        "app.chat_runtime.urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(
            b'{"output_text":"hello from provider"}'
        ),
    )

    response = _chat(tenant_id, "hello")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "COMPLETED_UNVERIFIED"
    assert result["verified"] is False
    assert result["message"] == "hello from provider"
    assert result["model"]

    payload = _one_trusted_record(tenant_id, result, "chat.completed")
    assert payload["message_count"] == 1
    assert payload["response_digest"] == hashlib.sha256(
        b"hello from provider"
    ).hexdigest()
    assert datetime.fromisoformat(payload["observed_at_utc"]).utcoffset().total_seconds() == 0
    assert "hello from provider" not in row_json(payload)
    assert "hello" not in row_json(payload)
    assert "test-only-placeholder" not in row_json(payload)


def test_chat_fails_closed_when_evidence_writer_is_unavailable(monkeypatch):
    tenant_id = _seed_tenant()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def broken_append(*args, **kwargs):
        raise RuntimeError("simulated evidence writer outage")

    monkeypatch.setattr("app.main.append_record", broken_append)
    with pytest.raises(RuntimeError, match="simulated evidence writer outage"):
        _chat(tenant_id)


def row_json(payload):
    return json.dumps(payload, sort_keys=True)
