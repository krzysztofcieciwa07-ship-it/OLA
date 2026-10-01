# OLA di-OS LLM Ecosystem

OLA keeps LLM providers behind one evidence-aware gateway. Provider selection is controlled by environment variables; API keys are never stored in source or evidence payloads.

## Providers

- openai — OpenAI Responses API
- ollama — local Ollama
- openrouter — OpenAI-compatible gateway
- mistral — Mistral OpenAI-compatible API
- groq — Groq OpenAI-compatible API
- together — Together OpenAI-compatible API
- deepseek — DeepSeek OpenAI-compatible API
- xai — xAI OpenAI-compatible API
- anthropic — Anthropic Messages API
- gemini — Google Gemini API

## Runtime controls

- OLA_LLM_PROVIDER
- OLA_LLM_MODEL
- OLA_LLM_MODE=deterministic|required
- OLA_LLM_TIMEOUT
- OLA_LLM_BASE_URL for OpenAI-compatible endpoints
- provider-specific API-key environment variables

## Evidence contract

Every real invocation records only non-secret provenance:

- provider
- model
- invocation type
- prompt digest
- response identifier
- agent instance/context evidence

A missing credential or failed required invocation returns BLOCK; OLA never silently upgrades an unavailable required LLM into a verified external inference.

The deterministic runtime remains available for local contract tests when OLA_LLM_MODE=deterministic.

## Capability endpoint

GET /llm/providers reports the provider registry and configured provider/model without exposing credentials.