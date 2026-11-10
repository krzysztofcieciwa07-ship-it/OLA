import json

import httpx
import pytest

from app.providers import (
    AgentModelOutput,
    OllamaAdapter,
    OpenAIAdapter,
    ProviderError,
    ProviderGateway,
)


MODEL = "qwen2.5:0.5b-instruct"
MODEL_DIGEST = "sha256:" + "a" * 64


def _output(**updates):
    value = {
        "status": "complete",
        "summary": "Calculation completed.",
        "reasoning": "The model proposed a bounded arithmetic operation.",
        "tool_name": None,
        "tool_arguments": {},
        "evidence_refs": [],
    }
    value.update(updates)
    return value


def _ollama_client(output=None, *, status=200, tags=None):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags or {
                "models": [{"name": MODEL, "digest": MODEL_DIGEST}],
            })
        if request.url.path == "/api/chat":
            body = {
                "model": MODEL,
                "id": "ollama-request-001",
                "message": {"content": json.dumps(output or _output())},
            }
            return httpx.Response(status, json=body)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_ollama_uses_json_schema_and_records_model_digest():
    client, calls = _ollama_client()
    adapter = OllamaAdapter(
        model=MODEL,
        allowed_models=(MODEL,),
        base_url="http://127.0.0.1:11434",
        client=client,
    )
    gateway = ProviderGateway(ollama=adapter)

    result = gateway.generate(
        provider="ollama",
        policy="local_read_only",
        prompt="Calculate 17 * 23.",
    )

    chat_call = next(call for call in calls if call.url.path == "/api/chat")
    payload = json.loads(chat_call.content)
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["format"] == AgentModelOutput.model_json_schema()
    assert result.provider == "ollama"
    assert result.model == MODEL
    assert result.model_digest == MODEL_DIGEST
    assert result.fallback_used is False
    assert result.model_output_role == "advisory_only"
    assert result.output.status == "complete"
    assert len(result.output_digest) == 64


def test_provider_policy_rejects_disallowed_provider_before_network_call():
    client, calls = _ollama_client()
    adapter = OllamaAdapter(
        model=MODEL,
        allowed_models=(MODEL,),
        base_url="http://127.0.0.1:11434",
        client=client,
    )
    gateway = ProviderGateway(ollama=adapter)

    with pytest.raises(ProviderError, match="not allowed"):
        gateway.generate(
            provider="openai",
            policy="local_read_only",
            prompt="private data",
        )

    assert calls == []


def test_provider_failure_does_not_fall_back_to_another_provider():
    client, calls = _ollama_client(status=503)
    adapter = OllamaAdapter(
        model=MODEL,
        allowed_models=(MODEL,),
        base_url="http://127.0.0.1:11434",
        client=client,
    )
    gateway = ProviderGateway(ollama=adapter)

    with pytest.raises(ProviderError) as error:
        gateway.generate(
            provider="ollama",
            policy="run_policy",
            prompt="run task",
        )

    assert error.value.code == "ollama_request_failed"
    assert len(calls) == 2


def test_ollama_model_must_be_allowlisted_and_present_with_digest():
    with pytest.raises(ProviderError) as error:
        OllamaAdapter(model=MODEL, allowed_models=("another-model",))
    assert error.value.code == "model_not_allowlisted"

    client, _ = _ollama_client(tags={"models": []})
    adapter = OllamaAdapter(
        model=MODEL,
        allowed_models=(MODEL,),
        base_url="http://127.0.0.1:11434",
        client=client,
    )
    with pytest.raises(ProviderError) as error:
        adapter.generate(prompt="test", schema=AgentModelOutput.model_json_schema())
    assert error.value.code == "model_not_installed"


def test_ollama_remote_endpoint_requires_explicit_host_allowlist():
    with pytest.raises(ProviderError) as error:
        OllamaAdapter(
            model=MODEL,
            allowed_models=(MODEL,),
            base_url="http://192.0.2.10:11434",
        )
    assert error.value.code == "endpoint_not_allowlisted"


def test_openai_uses_strict_json_schema_and_does_not_leak_api_key():
    api_key = "sk-test-secret-do-not-persist"
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["response_format"]["json_schema"]["schema"] == AgentModelOutput.model_json_schema()
        assert request.headers["Authorization"] == f"Bearer {api_key}"
        return httpx.Response(200, json={
            "id": "chatcmpl-test-001",
            "model": "gpt-4.1-2025-04-14",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps(_output())},
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenAIAdapter(
        model="gpt-4.1-2025-04-14",
        allowed_models=("gpt-4.1-2025-04-14",),
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        client=client,
    )
    gateway = ProviderGateway(openai=adapter)

    result = gateway.generate(
        provider="openai",
        policy="run_policy",
        prompt="Produce a bounded plan.",
    )

    serialized = result.model_dump_json()
    assert result.provider == "openai"
    assert result.model_digest is None
    assert result.request_id == "chatcmpl-test-001"
    assert api_key not in serialized
    assert len(calls) == 1


def test_openai_requires_key_and_model_allowlist():
    with pytest.raises(ProviderError) as error:
        OpenAIAdapter(
            model="gpt-4.1-2025-04-14",
            allowed_models=("gpt-4.1-2025-04-14",),
            api_key="",
        )
    assert error.value.code == "api_key_missing"

    with pytest.raises(ProviderError) as error:
        OpenAIAdapter(
            model="gpt-4.1",
            allowed_models=("gpt-4.1-2025-04-14",),
            api_key="sk-test",
        )
    assert error.value.code == "model_not_allowlisted"


def test_gateway_rejects_invalid_schema_and_unapproved_tool_request():
    client, _ = _ollama_client(output={
        "status": "needs_tool",
        "summary": "Need a tool.",
        "reasoning": "The model wants to run a shell.",
        "tool_name": "shell.exec",
        "tool_arguments": {"command": "whoami"},
        "evidence_refs": [],
    })
    adapter = OllamaAdapter(
        model=MODEL,
        allowed_models=(MODEL,),
        base_url="http://127.0.0.1:11434",
        client=client,
    )
    gateway = ProviderGateway(ollama=adapter)

    with pytest.raises(ProviderError) as error:
        gateway.generate(
            provider="ollama",
            policy="run_policy",
            prompt="Do something.",
            allowed_tools=("repo.read",),
        )
    assert error.value.code == "tool_not_allowlisted"


def test_source_provenance_policy_requires_evidence_references():
    client, _ = _ollama_client()
    adapter = OllamaAdapter(
        model=MODEL,
        allowed_models=(MODEL,),
        base_url="http://127.0.0.1:11434",
        client=client,
    )
    gateway = ProviderGateway(ollama=adapter)

    with pytest.raises(ProviderError) as error:
        gateway.generate(
            provider="ollama",
            policy="source_provenance_required",
            prompt="Research the topic.",
        )
    assert error.value.code == "evidence_refs_required"
