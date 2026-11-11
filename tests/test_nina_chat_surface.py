from app.api_key_hashing import api_key_fingerprint
import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiKey, Tenant
from app.main import app


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


def test_chat_runtime_persists_evidence_without_api_composition_root(monkeypatch):
    from app import chat_runtime
    import json

    tenant_id = "architecture-boundary-tenant"
    response_text = "chat result"
    persisted = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"output_text": response_text}).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://api.openai.com/v1/responses"
        assert timeout == 45
        return FakeResponse()

    def fake_append(tenant, record_type, payload, **kwargs):
        persisted.append((tenant, record_type, payload, kwargs))

    monkeypatch.setenv("OPENAI_API_KEY", "test-chat-key")
    monkeypatch.setenv("NINA_CHAT_MODEL", "architecture-test-model")
    monkeypatch.setattr(chat_runtime.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(chat_runtime, "append_evidence_atomic", fake_append)

    result = chat_runtime.chat(
        tenant_id,
        [{"role": "user", "content": "hello"}],
    )

    assert result == {
        "status": "VERIFIED",
        "message": response_text,
        "model": "architecture-test-model",
    }
    assert len(persisted) == 1
    event_tenant, record_type, payload, kwargs = persisted[0]
    assert event_tenant == tenant_id
    assert record_type == "chat.completed"
    assert payload == {
        "model": "architecture-test-model",
        "message_count": 1,
        "response_digest": hashlib.sha256(response_text.encode()).hexdigest(),
    }
    assert kwargs == {"deduplicate": False}
