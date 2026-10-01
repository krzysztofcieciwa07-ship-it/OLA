from app.llm_gateway import LLMGateway, supported_providers

def test_supported_llm_ecosystem_is_explicit():
    assert {"openai","ollama","openrouter","mistral","groq","together","deepseek","xai","anthropic","gemini"}.issubset(set(supported_providers()))

def test_required_provider_key_missing_fails_closed(monkeypatch):
    providers=[("openai","OPENAI_API_KEY"),("openrouter","OPENROUTER_API_KEY"),("mistral","MISTRAL_API_KEY"),("groq","GROQ_API_KEY"),("together","TOGETHER_API_KEY"),("deepseek","DEEPSEEK_API_KEY"),("xai","XAI_API_KEY"),("anthropic","ANTHROPIC_API_KEY"),("gemini","GEMINI_API_KEY")]
    for provider,key in providers:
        monkeypatch.setenv("OLA_LLM_PROVIDER",provider); monkeypatch.setenv("OLA_LLM_MODE","required"); monkeypatch.delenv(key,raising=False)
        assert LLMGateway().invoke("nina","hello",{}).status=="BLOCK"

def test_ollama_requires_no_api_key(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER","ollama"); monkeypatch.setenv("OLA_LLM_MODE","required"); monkeypatch.delenv("OLLAMA_API_KEY",raising=False)
    assert LLMGateway().provider_config().api_key_env is None

def test_custom_base_url_requires_allowlist(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER","openrouter"); monkeypatch.setenv("OLA_LLM_BASE_URL","http://127.0.0.1:9999/v1"); monkeypatch.setenv("OLA_LLM_ALLOW_CUSTOM_BASE_URL","true"); monkeypatch.setenv("OLA_LLM_MODE","required"); monkeypatch.setenv("OPENROUTER_API_KEY","test-key")
    result=LLMGateway().invoke("nina","hello",{}); assert result.status=="BLOCK" and "allowlisted" in result.reason

def test_openrouter_invocation_is_received_not_verified(monkeypatch):
    monkeypatch.setenv("OLA_LLM_PROVIDER","openrouter"); monkeypatch.setenv("OLA_LLM_MODE","required"); monkeypatch.setenv("OPENROUTER_API_KEY","test-key")
    import app.llm_gateway as module
    class Response:
        content=b'{"id":"resp-test","choices":[{"message":{"content":"ok"}}]}'
        def raise_for_status(self): pass
        def json(self): return {"id":"resp-test","choices":[{"message":{"content":"ok"}}]}
    calls=[]; monkeypatch.setattr(module.httpx,"post",lambda url,**kwargs:(calls.append((url,kwargs)) or Response()))
    result=module.LLMGateway().invoke("nina","hello",{})
    assert result.status=="RECEIVED" and result.provider=="openrouter" and result.response_id=="resp-test"
    assert calls[0][0].endswith("/chat/completions") and "test-key" not in repr(result)


# Regression: a real LLM RECEIVED result must remain runtime evidence.
def test_agent_runtime_accepts_received_llm_result(monkeypatch):
    import app.llm_gateway as gateway_module
    import app.agent_runtime as runtime_module

    received = gateway_module.LLMResult(
        status="RECEIVED",
        provider="openrouter",
        model="test-model",
        invocation_type="real_llm",
        prompt_digest="d" * 64,
        output="ok",
        response_id="resp-test",
    )
    monkeypatch.setattr(
        gateway_module.LLMGateway,
        "invoke",
        lambda self, agent, task, context: received,
    )
    result = runtime_module._invoke_llm("nina", "hello", {})
    assert result is not None
    assert result["provider"] == "openrouter"
    assert result["invocation_type"] == "real_llm"
    assert result["response_id"] == "resp-test"

# CI synchronization marker: rerun against current main workflow snapshot.
