"""Provider-neutral LLM gateway for OLA di-OS.

The gateway keeps model-provider concerns outside NINA/IGOR execution logic.
It supports hosted and local providers without putting credentials in source,
and every successful invocation returns provenance fields suitable for the
existing evidence hash-chain.
"""

from dataclasses import dataclass
import hashlib
import json
import os

import httpx


OPENAI_COMPATIBLE = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "together": ("TOGETHER_API_KEY", "https://api.together.xyz/v1"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1"),
    "xai": ("XAI_API_KEY", "https://api.x.ai/v1"),
}
SPECIALIZED = {"anthropic", "gemini"}
LOCAL = {"ollama"}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    base_url: str
    api_key_env: str | None


@dataclass(frozen=True)
class LLMResult:
    status: str
    reason: str | None = None
    provider: str | None = None
    model: str | None = None
    invocation_type: str | None = None
    prompt_digest: str | None = None
    output: str | None = None
    response_id: str | None = None


def supported_providers():
    return tuple(sorted((*OPENAI_COMPATIBLE, *SPECIALIZED, *LOCAL)))


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LLMGateway:
    def __init__(self, env=None):
        self.env = os.environ if env is None else env

    def provider_config(self):
        provider = self.env.get("OLA_LLM_PROVIDER", "openai").strip().lower()
        defaults = {
            "openai": "gpt-5.6-luna",
            "openrouter": "openai/gpt-5.6-luna",
            "mistral": "mistral-small-latest",
            "groq": "llama-3.3-70b-versatile",
            "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "deepseek": "deepseek-chat",
            "xai": "grok-4-fast-reasoning",
            "anthropic": "claude-sonnet-4-5",
            "gemini": "gemini-2.5-flash",
            "ollama": "qwen2.5:0.5b-instruct",
        }
        model = self.env.get("OLA_LLM_MODEL") or self.env.get("NINA_CHAT_MODEL") or defaults.get(provider, "")
        if provider in OPENAI_COMPATIBLE:
            key_env, base = OPENAI_COMPATIBLE[provider]
            base = self.env.get("OLA_LLM_BASE_URL", base).rstrip("/")
            return ProviderConfig(provider, model, base, key_env)
        if provider == "ollama":
            return ProviderConfig(provider, model, self.env.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"), None)
        if provider == "anthropic":
            return ProviderConfig(provider, model, self.env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"), "ANTHROPIC_API_KEY")
        if provider == "gemini":
            return ProviderConfig(provider, model, self.env.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/"), "GEMINI_API_KEY")
        return ProviderConfig(provider, model, "", None)

    def _required(self):
        return self.env.get("OLA_LLM_MODE", "deterministic").strip().lower() == "required"

    def invoke(self, agent, task, context):
        cfg = self.provider_config()
        prompt = json.dumps({"agent": agent, "task": task, "context": context}, sort_keys=True, separators=(",", ":"))
        prompt_digest = _digest(prompt)
        if cfg.provider not in supported_providers():
            if self._required():
                return LLMResult("BLOCK", f"unsupported LLM provider: {cfg.provider}")
            return LLMResult("SKIPPED", f"unsupported LLM provider: {cfg.provider}")
        if cfg.api_key_env and not self.env.get(cfg.api_key_env):
            if self._required():
                return LLMResult("BLOCK", f"{cfg.api_key_env} API key is missing")
            return LLMResult("SKIPPED", f"{cfg.api_key_env} API key is missing")

        system = (
            "You are one agent in OLA di-OS. Return concise JSON-compatible reasoning output. "
            "Do not claim tools or evidence you did not actually use."
        )
        try:
            if cfg.provider in OPENAI_COMPATIBLE:
                result = self._openai_compatible(cfg, system, prompt)
            elif cfg.provider == "ollama":
                result = self._ollama(cfg, system, prompt)
            elif cfg.provider == "anthropic":
                result = self._anthropic(cfg, system, prompt)
            elif cfg.provider == "gemini":
                result = self._gemini(cfg, system, prompt)
            else:
                raise RuntimeError(f"unsupported LLM provider: {cfg.provider}")
        except (httpx.HTTPError, ValueError, KeyError, RuntimeError) as exc:
            if self._required():
                return LLMResult("BLOCK", f"LLM invocation failed: {exc.__class__.__name__}", cfg.provider, cfg.model, "real_llm", prompt_digest)
            return LLMResult("SKIPPED", f"LLM invocation failed: {exc.__class__.__name__}", cfg.provider, cfg.model, "real_llm", prompt_digest)

        return LLMResult(
            status="VERIFIED",
            provider=cfg.provider,
            model=cfg.model,
            invocation_type="real_llm",
            prompt_digest=prompt_digest,
            output=result["output"],
            response_id=result.get("response_id"),
        )

    @staticmethod
    def _openai_compatible(cfg, system, prompt):
        response = httpx.post(
            cfg.base_url + "/responses",
            headers={"Authorization": f"Bearer {os.environ[cfg.api_key_env]}", "Content-Type": "application/json"},
            json={"model": cfg.model, "input": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            timeout=float(os.getenv("OLA_LLM_TIMEOUT", "60")),
        )
        response.raise_for_status()
        body = response.json()
        output = body.get("output_text")
        if not output:
            parts = []
            for item in body.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") in {"output_text", "text"} and part.get("text"):
                        parts.append(part["text"])
            output = "\n".join(parts)
        if not output:
            raise ValueError("provider returned no output text")
        return {"output": output, "response_id": body.get("id")}

    @staticmethod
    def _ollama(cfg, system, prompt):
        response = httpx.post(
            cfg.base_url + "/api/chat",
            headers={"Content-Type": "application/json"},
            json={"model": cfg.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "stream": False, "options": {"temperature": 0}},
            timeout=float(os.getenv("OLA_LLM_TIMEOUT", "60")),
        )
        response.raise_for_status()
        body = response.json()
        output = body.get("message", {}).get("content")
        if not output:
            raise ValueError("Ollama returned no message content")
        return {"output": output, "response_id": body.get("id") or f"ollama:{_digest(json.dumps(body, sort_keys=True))}"}

    @staticmethod
    def _anthropic(cfg, system, prompt):
        response = httpx.post(
            cfg.base_url + "/v1/messages",
            headers={"x-api-key": os.environ[cfg.api_key_env], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": cfg.model, "max_tokens": 1024, "system": system, "messages": [{"role": "user", "content": prompt}]},
            timeout=float(os.getenv("OLA_LLM_TIMEOUT", "60")),
        )
        response.raise_for_status()
        body = response.json()
        parts = [part.get("text", "") for part in body.get("content", []) if part.get("type") == "text"]
        output = "\n".join(part for part in parts if part)
        if not output:
            raise ValueError("Anthropic returned no text")
        return {"output": output, "response_id": body.get("id")}

    @staticmethod
    def _gemini(cfg, system, prompt):
        key = os.environ[cfg.api_key_env]
        response = httpx.post(
            f"{cfg.base_url}/v1beta/models/{cfg.model}:generateContent?key={key}",
            headers={"content-type": "application/json"},
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}]},
            timeout=float(os.getenv("OLA_LLM_TIMEOUT", "60")),
        )
        response.raise_for_status()
        body = response.json()
        parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        output = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        if not output:
            raise ValueError("Gemini returned no text")
        return {"output": output, "response_id": body.get("responseId") or f"gemini:{_digest(json.dumps(body, sort_keys=True))}"}
