"""Bounded live Ollama generation must remain a REAL model invocation."""
from unittest.mock import Mock, patch
import httpx
import pytest
from app.agent_runtime import _invoke_llm

_BASE_ENV = {
    "OLA_LLM_PROVIDER": "ollama",
    "OLA_LLM_MODE": "required",
    "OLA_LLM_MODEL": "qwen2.5:0.5b-instruct",
    "OLA_LLM_TIMEOUT": "60",
}

def _fake_response():
    response = Mock()
    response.json.return_value = {"message": {"content": "real response"}, "id": "call-42"}
    return response

def test_bounded_generation_is_forwarded_to_real_ollama_transport():
    env = {**_BASE_ENV, "OLA_OLLAMA_NUM_PREDICT": "96"}
    with patch.dict("os.environ", env, clear=True), patch("httpx.post", return_value=_fake_response()) as post:
        result = _invoke_llm("codeact", "Calculate 17 * 23", {})
    assert post.call_count == 1
    args, kwargs = post.call_args
    assert args[0] == "http://127.0.0.1:11434/api/chat"
    assert kwargs["json"]["options"] == {"temperature": 0, "num_predict": 96}
    assert kwargs["json"]["stream"] is False
    assert result["provider"] == "ollama"
    assert result["invocation_type"] == "real_llm"
    assert result["response_id"] == "call-42"

def test_unconfigured_budget_preserves_existing_behavior():
    with patch.dict("os.environ", _BASE_ENV, clear=True), patch("httpx.post", return_value=_fake_response()) as post:
        _invoke_llm("react", "test", {})
    assert post.call_args.kwargs["json"]["options"] == {"temperature": 0}

@pytest.mark.parametrize("budget", ["", "0", "-1", "513", "10.5", " 96", "true", "inf", "NaN"])
def test_invalid_budgets_block_before_network(budget):
    env = {**_BASE_ENV, "OLA_OLLAMA_NUM_PREDICT": budget}
    with patch.dict("os.environ", env, clear=True), patch("httpx.post") as post:
        with pytest.raises(ValueError, match="OLA_OLLAMA_NUM_PREDICT"):
            _invoke_llm("agentic_rag", "test", {})
    post.assert_not_called()

def test_provider_timeout_fails_closed_without_deterministic_fallback():
    env = {**_BASE_ENV, "OLA_OLLAMA_NUM_PREDICT": "96"}
    with patch.dict("os.environ", env, clear=True), patch("httpx.post", side_effect=httpx.ReadTimeout("provider slow")) as post:
        with pytest.raises(httpx.ReadTimeout):
            _invoke_llm("codeact", "test", {})
    post.assert_called_once()
