# OLA di-OS — Hugging Face provider (opt-in)

The existing `app.agent_runtime._invoke_llm` and `app.chat_runtime.chat` now use
the same `app.huggingface_runtime.invoke_huggingface_chat` adapter when selected.
The default OpenAI and Ollama paths are unchanged. No automatic fallback to
Hugging Face takes place.

## Runtime configuration

Set the following values **in the OLA application process/container**, not
only in a separate PowerShell window:

```text
OLA_HF_ALLOW_CLOUD=1
HF_TOKEN=<private Hugging Face token, stored in a secret manager>
OLA_HF_MODELS=zai-org/GLM-5.3:novita
OLA_HF_MAX_TOKENS=512
OLA_LLM_PROVIDER=huggingface
OLA_LLM_MODEL=zai-org/GLM-5.3:novita
OLA_LLM_MODE=required
NINA_CHAT_PROVIDER=huggingface
NINA_CHAT_MODEL=zai-org/GLM-5.3:novita
```

`OLA_HF_ALLOW_CLOUD` is a required explicit approval to transmit prompts to
an external provider. Leave unset for private/local workloads. Model selection
is allowlisted, output tokens are capped to 2048 per request, and errors are
redacted. HTTP timeout is controlled by `OLA_LLM_TIMEOUT` for the agent
pipeline (60 seconds by default); NINA chat has a 45-second timeout.

Never commit `HF_TOKEN` or place it in a URL. The token set by `$env:HF_TOKEN`
in interactive PowerShell is scoped to that session; remote Docker/Replit/CI
deployments do not inherit it. Configure a dedicated runtime secret separately.

## Local evidence and verification

```bash
pytest -q tests/test_huggingface_runtime.py
```

Offline tests mock the network and require no `HF_TOKEN` or provider charges.
They prove policy, error handling, response provenance and record hashing.
They **do not** prove that a live HF credential, quotas or upstream Novita
endpoint work. Obtain a separate live smoke-test result and attach redacted
evidence before promotion. A remote LLM response is `RECORDED`, not
independently signed or approved for execution. IGOR and Human Gate remain
separate production checks.
