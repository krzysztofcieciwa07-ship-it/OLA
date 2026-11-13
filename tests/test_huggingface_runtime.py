"""Offline regression tests: no API credentials or network required."""

import hashlib

import httpx
import pytest

from app.agent_runtime import _invoke_llm
from app.huggingface_runtime import DEFAULT_MODEL, invoke_huggingface_chat


def _allow(monkeypatch):
    monkeypatch.setenv("OLA_HF_ALLOW_CLOUD", "1")
    monkeypatch.setenv("HF_TOKEN", "hf_test_not_a_real_credential")
    monkeypatch.setenv("OLA_HF_MAX_TOKENS", "128")
    monkeypatch.delenv("OLA_HF_MODELS", raising=False)


def _fake_response(status_code=200, body=None):
    payload = body if body is not None else {
        "id": "chatcmpl-test-1",
        "choices": [{"message": {"role": "assistant", "content": "Paris"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://router.huggingface.co/v1/chat/completions"),
    )


def test_cloud_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OLA_HF_ALLOW_CLOUD", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_test_not_a_real_credential")
    with pytest.raises(RuntimeError, match="OLA_HF_ALLOW_CLOUD=1"):
        invoke_huggingface_chat(model=DEFAULT_MODEL, messages=[{"role": "user", "content": "test"}], timeout=2)


def test_missing_token_fails_closed(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="HF_TOKEN is not configured"):
        invoke_huggingface_chat(model=DEFAULT_MODEL, messages=[{"role": "user", "content": "test"}], timeout=2)


def test_unapproved_model_never_makes_request(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr("app.huggingface_runtime.httpx.post", lambda *a, **k: pytest.fail("network must be blocked"))
    with pytest.raises(RuntimeError, match="allowlist"):
        invoke_huggingface_chat(model="unapproved/provider", messages=[{"role": "user", "content": "test"}], timeout=2)


@pytest.mark.parametrize("budget", ["0", "2049", "invalid", "1.5"])
def test_invalid_budget_fails_closed(monkeypatch, budget):
    _allow(monkeypatch)
    monkeypatch.setenv("OLA_HF_MAX_TOKENS", budget)
    with pytest.raises(RuntimeError, match="OLA_HF_MAX_TOKENS"):
        invoke_huggingface_chat(model=DEFAULT_MODEL, messages=[{"role": "user", "content": "test"}], timeout=2)


def test_success_returns_provenance_without_secret(monkeypatch):
    _allow(monkeypatch)
    observed = {}

    def fake_post(url, **kwargs):
        observed.update({"url": url, **kwargs})
        return _fake_response()

    monkeypatch.setattr("app.huggingface_runtime.httpx.post", fake_post)
    output = invoke_huggingface_chat(
        model=DEFAULT_MODEL, messages=[{"role": "user", "content": "France?"}], timeout=5,
    )
    assert output["output"] == "Paris"
    assert output["response_id"] == "chatcmpl-test-1"
    assert output["model"] == DEFAULT_MODEL
    assert output["usage"]["completion_tokens"] == 2
    assert observed["json"]["max_tokens"] == 128
    assert observed["json"]["model"] == DEFAULT_MODEL
    assert "hf_test_not_a_real_credential" not in str(output)


def test_http_error_redacts_provider_body(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(
        "app.huggingface_runtime.httpx.post",
        lambda *a, **k: _fake_response(401, {"error": "hf_secret_must_not_leak"}),
    )
    with pytest.raises(RuntimeError, match="Hugging Face inference failed") as error:
        invoke_huggingface_chat(model=DEFAULT_MODEL, messages=[{"role": "user", "content": "test"}], timeout=2)
    assert "hf_secret_must_not_leak" not in str(error.value)


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"id": "id", "choices": [{"message": {"content": ""}}]}, {"choices": [{"message": {"content": "Paris"}}]}])
def test_missing_or_empty_completion_is_not_verified(monkeypatch, body):
    _allow(monkeypatch)
    monkeypatch.setattr("app.huggingface_runtime.httpx.post", lambda *a, **k: _fake_response(body=body))
    with pytest.raises(RuntimeError, match="Hugging Face returned"):
        invoke_huggingface_chat(model=DEFAULT_MODEL, messages=[{"role": "user", "content": "test"}], timeout=2)


def test_agent_pipeline_uses_shared_adapter(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setenv("OLA_LLM_PROVIDER", "huggingface")
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.setenv("OLA_LLM_MODEL", DEFAULT_MODEL)
    monkeypatch.setattr("app.huggingface_runtime.httpx.post", lambda *a, **k: _fake_response())

    output = _invoke_llm("codeact", "Calculate 2 + 2", {"tenant": "sample"})
    assert output["provider"] == "huggingface"
    assert output["invocation_type"] == "real_llm"
    assert output["model"] == DEFAULT_MODEL
    assert output["response_id"] == "chatcmpl-test-1"
    assert len(output["prompt_digest"]) == len(hashlib.sha256(b"").hexdigest())
    assert output["output"] == "Paris"


def test_nina_chat_uses_shared_adapter_and_audit_digest(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setenv("NINA_CHAT_PROVIDER", "huggingface")
    monkeypatch.setenv("NINA_CHAT_MODEL", DEFAULT_MODEL)
    monkeypatch.setattr("app.huggingface_runtime.httpx.post", lambda *a, **k: _fake_response())

    from app import main
    from app.chat_runtime import chat

    evidence = []
    monkeypatch.setattr(main, "append_record", lambda tenant, kind, body: evidence.append((tenant, kind, body)))
    response = chat("tenant-1", [{"role": "user", "content": "France?"}])
    assert response["message"] == "Paris"
    assert response["provider"] == "huggingface"
    assert response["evidence_level"] == "RECORDED"
    assert evidence[0][0:2] == ("tenant-1", "chat.completed")
    assert evidence[0][2]["response_digest"] == hashlib.sha256(b"Paris").hexdigest()
    assert "hf_test_not_a_real_credential" not in str(evidence)
