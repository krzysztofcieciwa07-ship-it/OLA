from app.llm_gateway import LLMGateway, supported_providers


def test_supported_llm_ecosystem_is_explicit():
    expected = {"openai", "ollama", "openrouter", "mistral", "groq", "together", "deepseek", "xai", "anthropic", "gemini"}
    assert expected.issubset(set(supported_providers()))


def test_gateway_fails_closed_when_required_provider_key_missing(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    gateway = LLMGateway()
    result = gateway.invoke("nina", "hello", {})
    assert result.status == "BLOCK"
    assert "API key" in result.reason


def test_openai_compatible_provider_can_be_selected(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OLA_LLM_MODEL", "openai/gpt-5.6-luna")
    gateway = LLMGateway()
    assert gateway.provider_config().provider == "openrouter"
    assert gateway.provider_config().model == "openai/gpt-5.6-luna"


def test_ollama_is_local_and_needs_no_api_key(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    gateway = LLMGateway()
    assert gateway.provider_config().provider == "ollama"

def test_openrouter_invocation_uses_chat_completions(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OLA_LLM_MODE", "required")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OLA_LLM_MODEL", "openai/gpt-5.6-luna")

    import app.llm_gateway as module

    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"id": "resp-test", "choices": [{"message": {"content": "ok"}}]}

    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(module.httpx, "post", fake_post)
    result = module.LLMGateway().invoke("nina", "hello", {})
    assert result.status == "VERIFIED"
    assert result.provider == "openrouter"
    assert result.response_id == "resp-test"
    assert calls[0][0].endswith("/chat/completions")
