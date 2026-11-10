import hashlib
import json
import os
import time
from urllib.parse import urlsplit

import httpx

from .contracts import ProviderError


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _validate_base_url(base_url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or host not in {item.lower() for item in allowed_hosts}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderError("endpoint_not_allowlisted", "OpenAI endpoint is outside the HTTPS allowlist")
    return base_url.rstrip("/")


class OpenAIAdapter:
    def __init__(
        self,
        *,
        model: str | None = None,
        allowed_models: tuple[str, ...] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.model = model if model is not None else os.getenv("OLA_OPENAI_MODEL", "").strip()
        self.allowed_models = tuple(item.strip() for item in allowed_models if item.strip()) if allowed_models is not None else _csv_env("OLA_OPENAI_ALLOWED_MODELS")
        if not self.model or not self.allowed_models or self.model not in self.allowed_models:
            raise ProviderError("model_not_allowlisted", "OpenAI model must be explicitly allowlisted")
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError("api_key_missing", "OPENAI_API_KEY is required for the OpenAI provider")
        self.allowed_hosts = tuple(item.strip() for item in allowed_hosts if item.strip()) if allowed_hosts is not None else _csv_env("OLA_OPENAI_ALLOWED_HOSTS", "api.openai.com")
        self.base_url = _validate_base_url(
            base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            self.allowed_hosts,
        )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.Client(timeout=timeout_seconds, trust_env=False)

    def generate(self, *, prompt: str, schema: dict, schema_name: str = "ola_agent_output_v1") -> dict:
        if not isinstance(prompt, str) or not prompt or len(prompt.encode("utf-8")) > 32768:
            raise ProviderError("prompt_invalid", "prompt must be non-empty and at most 32 KiB")
        started = time.monotonic()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only JSON matching the supplied schema. Model output is advisory and never authorizes side effects.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
            "temperature": 0,
        }
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("model") != self.model:
                raise ProviderError("model_identity_mismatch", "OpenAI returned an unexpected model")
            choices = body.get("choices") or []
            if not choices or choices[0].get("finish_reason") != "stop":
                raise ProviderError("incomplete_model_output", "OpenAI response was incomplete or filtered")
            content = choices[0].get("message", {}).get("content")
            if not isinstance(content, str) or not content:
                raise ProviderError("empty_model_output", "OpenAI returned no structured content")
            try:
                output = json.loads(content)
            except json.JSONDecodeError:
                raise ProviderError("invalid_model_json", "OpenAI response was not valid JSON") from None
            raw_digest = hashlib.sha256(response.content).hexdigest()
            return {
                "data": output,
                "model": self.model,
                "model_digest": None,
                "request_id": str(body.get("id") or f"openai:{raw_digest}"),
                "request_id_source": "provider",
                "provider_response_id": body.get("id") if isinstance(body.get("id"), str) else None,
                "raw_response_digest": raw_digest,
                "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
            }
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ProviderError("openai_request_failed", "OpenAI request failed closed") from exc

    def close(self) -> None:
        self.client.close()
