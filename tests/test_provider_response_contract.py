"""Real chat/runtime/API boundaries, disposable SQLite and stubbed provider HTTP.

No external model, workstation action or production assurance is exercised.
"""
import hashlib
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import agent_runtime
from app.api_key_crypto import hash_api_key
from app.chat_runtime import _real_chat, chat
from app.database import SessionLocal
from app.hashchain import canonical_json
from app.main import app
from app.models import ApiKey, EvidenceRecord, Tenant

MARKER = "PRIVATE_PROVIDER_PAYLOAD_MUST_NOT_ENTER_ERROR_OR_EVIDENCE"
TOOLS = ("safe_expression", "local_mcp_tool_registry.sha256")


def provider_config(monkeypatch, provider):
    monkeypatch.setenv("OLA_CHAT_PROVIDER", provider)
    monkeypatch.setenv("OLA_LLM_PROVIDER", provider)
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.setenv("OLA_CHAT_MODEL", "isolated-provider-test")
    monkeypatch.setenv("OLA_LLM_MODEL", "isolated-provider-test")
    monkeypatch.setenv("OPENAI_API_KEY", "PUBLIC_TEST_KEY_NOT_A_REAL_CREDENTIAL")
    monkeypatch.delenv("OLA_OLLAMA_NUM_PREDICT", raising=False)


def provider_response(payload):
    # json=None in HTTPX means an absent request body, not a literal JSON null.
    return httpx.Response(200, content=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"},
                          request=httpx.Request("POST", "https://provider.invalid/test"))


def seed(with_key=False):
    tenant_id = str(uuid.uuid4())
    key = "isolated-provider-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="provider-contract"))
        db.flush()
        if with_key:
            db.add(ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id,
                          key_hash=hash_api_key(key)))
        db.commit()
    return tenant_id, key


def records(tenant_id):
    with SessionLocal() as db:
        return db.scalars(select(EvidenceRecord).where(
            EvidenceRecord.tenant_id == tenant_id).order_by(EvidenceRecord.seq)).all()


MALFORMED = [
    pytest.param(provider, payload, id=f"{provider}-root-{name}")
    for provider in ("ollama", "openai")
    for name, payload in (("null", None), ("list", []), ("string", MARKER),
                          ("number", 42), ("boolean", True))
] + [
    pytest.param("ollama", payload, id="ollama-" + name)
    for name, payload in (
        ("missing-message", {}),
        ("null-message", {"message": None}),
        ("list-message", {"message": []}),
        ("null-content", {"message": {"content": None}}),
        ("number-content", {"message": {"content": 123}}),
        ("list-content", {"message": {"content": [MARKER]}}),
        ("object-content", {"message": {"content": {"private": MARKER}}}),
        ("blank-content", {"message": {"content": " \n\t"}}),
        ("number-id", {"message": {"content": "text"}, "id": 123}),
        ("empty-id", {"message": {"content": "text"}, "id": ""}),
        ("blank-id", {"message": {"content": "text"}, "id": " \t"}),
    )
] + [
    pytest.param("openai", payload, id="openai-" + name)
    for name, payload in (
        ("null-output", {"id": "resp-test", "output": None}),
        ("null-output-item", {"id": "resp-test", "output": [None]}),
        ("null-content", {"id": "resp-test", "output": [{"content": None}]}),
        ("null-part", {"id": "resp-test", "output": [{"content": [None]}]}),
        ("number-part-text", {"id": "resp-test", "output": [{"content": [{"type": "output_text", "text": 123}]}]}),
        ("mixed-malformed-part", {"id": "resp-test", "output": [{"content": [{"type": "output_text", "text": "valid"}, {"type": "output_text", "text": [MARKER]}]}]}),
        ("number-output-text", {"id": "resp-test", "output_text": 123}),
        ("list-output-text", {"id": "resp-test", "output_text": [MARKER]}),
        ("blank-output-text", {"id": "resp-test", "output_text": " \n\t"}),
        ("missing-id", {"output_text": "valid"}),
        ("number-id", {"id": 123, "output_text": "valid"}),
        ("empty-id", {"id": "", "output_text": "valid"}),
        ("blank-id", {"id": " \t", "output_text": "valid"}),
    )
]


@pytest.mark.parametrize("provider,payload", MALFORMED)
def test_malformed_chat_blocks_without_success_evidence(monkeypatch, provider, payload):
    provider_config(monkeypatch, provider)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: provider_response(payload))
    tenant_id, _ = seed()
    result = chat(tenant_id, [{"role": "user", "content": "hello"}])
    assert result == {"status": "BLOCK", "reason": "configured chat provider unavailable or response invalid"}
    assert records(tenant_id) == []
    assert MARKER not in json.dumps(result)


@pytest.mark.parametrize("provider,payload", MALFORMED)
def test_malformed_agent_response_blocks_before_tools_or_fallback(monkeypatch, provider, payload):
    provider_config(monkeypatch, provider)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: provider_response(payload))
    tools_called = []
    monkeypatch.setattr(agent_runtime, "_safe_expression", lambda task: tools_called.append(task) or "391")
    monkeypatch.setattr(agent_runtime, "_invoke_local_deterministic_model",
                        lambda *a: pytest.fail("invalid provider data must not fall back to a local model"))
    tenant_id, _ = seed()
    result = agent_runtime.run_agent_task(tenant_id, "Calculate 17 * 23", allowed_tools=TOOLS)
    assert result["status"] == "BLOCK"
    assert result["final_result"] is None
    assert result["execution"] == []
    assert tools_called == []
    rows = records(tenant_id)
    assert [r.record_type for r in rows] == ["runtime.blocked"]
    assert json.loads(rows[0].payload_json)["reason_code"] == "MODEL_OR_TOOL_UNAVAILABLE"
    assert MARKER not in json.dumps(result) + rows[0].payload_json


@pytest.mark.parametrize("provider,payload,expected", [
    ("ollama", {"message": {"content": "  exact text\n"}, "done": True}, "  exact text\n"),
    ("ollama", {"message": {"content": "text"}, "id": None}, "text"),
    ("ollama", {"message": {"content": "text"}, "id": "ollama-call"}, "text"),
    ("openai", {"id": "resp-test", "output_text": "shortcut"}, "shortcut"),
    ("openai", {"id": "resp-test", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": "one"},
                                           {"type": "text", "text": "two"}]},
    ]}, "one\ntwo"),
    ("openai", {"id": "resp-test", "output_text": "", "output": [
        {"content": [{"type": "output_text", "text": "fallback"}]}]}, "fallback"),
])
def test_valid_response_has_same_exact_text_and_identity_for_chat_and_agent(monkeypatch, provider, payload, expected):
    provider_config(monkeypatch, provider)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: provider_response(payload))
    text, identity = _real_chat(provider, "isolated-provider-test", [{"role": "user", "content": "hello"}])
    invoked = agent_runtime._invoke_llm("codeact", "Calculate 17 * 23", {})
    assert text == invoked["output"] == expected
    if provider == "ollama" and payload.get("id") is None:
        expected_id = "ollama:" + hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    else:
        expected_id = payload["id"]
    assert identity == invoked["response_id"] == expected_id


def test_later_provider_failure_preserves_prior_evidence_without_completing_run(monkeypatch):
    provider_config(monkeypatch, "ollama")
    replies = iter([{"message": {"content": "valid first agent"}}, {"message": None}])
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: provider_response(next(replies)))
    tenant_id, _ = seed()
    result = agent_runtime.run_agent_task(tenant_id, "Calculate 17 * 23", allowed_tools=TOOLS)
    assert result["status"] == "BLOCK"
    assert len(result["execution"]) == 1
    assert result["execution"][0]["tool_output"] == "391"
    assert result["final_result"] is None
    rows = records(tenant_id)
    assert [r.record_type for r in rows] == ["agent.codeact", "runtime.blocked"]
    blocked = json.loads(rows[-1].payload_json)
    assert blocked["completed_agents"] == 1
    assert blocked["run_id"] == result["run_id"]


@pytest.mark.parametrize("endpoint", ["/chat", "/agent-run", "/nina-run"])
@pytest.mark.parametrize("provider,payload", [
    ("ollama", {"message": None}),
    ("ollama", {"message": {"content": [MARKER]}}),
    ("openai", {"id": "resp-test", "output": None}),
])
def test_api_returns_controlled_block_for_invalid_provider_payload(
        monkeypatch, local_binding_source, endpoint, provider, payload):
    # Real FastAPI/auth/SQLite. Only provider HTTP and /nina-run source observer are doubles.
    provider_config(monkeypatch, provider)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: provider_response(payload))
    tenant_id, key = seed(with_key=True)
    body = ({"messages": [{"role": "user", "content": "hello"}]} if endpoint == "/chat"
            else {"task": "Calculate 17 * 23", "requested_tools": list(TOOLS)})
    result = TestClient(app, raise_server_exceptions=False).post(
        endpoint, headers={"X-API-Key": key}, json=body)
    assert result.status_code == 200
    assert result.json()["status"] == "BLOCK"
    assert MARKER not in result.text
    assert not any(r.record_type == "chat.completed" or r.record_type.startswith("agent.")
                   for r in records(tenant_id))
