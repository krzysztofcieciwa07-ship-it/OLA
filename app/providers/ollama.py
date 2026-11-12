import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import urlsplit

import httpx

from .contracts import ProviderError


_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _validate_base_url(base_url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or host not in {item.lower() for item in allowed_hosts}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ProviderError("endpoint_not_allowlisted", "Ollama endpoint is outside the network allowlist")
    if parsed.scheme == "http" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ProviderError("insecure_remote_endpoint", "remote Ollama endpoints must use HTTPS")
    return base_url.rstrip("/")


class OllamaAdapter:
    def __init__(
        self,
        *,
        model: str | None = None,
        allowed_models: tuple[str, ...] | None = None,
        expected_model_digest: str | None = None,
        base_url: str | None = None,
        allowed_hosts: tuple[str, ...] | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.model = model if model is not None else os.getenv("OLA_OLLAMA_MODEL", "").strip()
        self.allowed_models = tuple(item.strip() for item in allowed_models if item.strip()) if allowed_models is not None else _csv_env("OLA_OLLAMA_ALLOWED_MODELS")
        if not self.model or not self.allowed_models or self.model not in self.allowed_models:
            raise ProviderError("model_not_allowlisted", "Ollama model must be explicitly allowlisted")
        self.expected_model_digest = (
            expected_model_digest if expected_model_digest is not None
            else os.getenv("OLA_OLLAMA_EXPECTED_MODEL_DIGEST", "").strip()
        )
        if not isinstance(self.expected_model_digest, str) or _DIGEST_PATTERN.fullmatch(self.expected_model_digest) is None:
            raise ProviderError("model_digest_not_pinned", "Ollama model digest must be pinned in the deployment lock")
        self.allowed_hosts = tuple(item.strip() for item in allowed_hosts if item.strip()) if allowed_hosts is not None else _csv_env(
            "OLA_OLLAMA_ALLOWED_HOSTS", "127.0.0.1,localhost,::1"
        )
        self.base_url = _validate_base_url(
            (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11435")).strip().rstrip("/"),
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
        gateway_request_id = f"ola-gateway:{uuid.uuid4()}"
        try:
            tags_response = self.client.get(
                f"{self.base_url}/api/tags",
                timeout=self.timeout_seconds,
            )
            tags_response.raise_for_status()
            tags_body = tags_response.json()
            models = tags_body.get("models", [])
            model_entry = next(
                (item for item in models if item.get("name") == self.model),
                None,
            )
            if model_entry is None:
                raise ProviderError("model_not_installed", "allowlisted Ollama model is not installed")
            model_digest = model_entry.get("digest")
            if not isinstance(model_digest, str) or _DIGEST_PATTERN.fullmatch(model_digest) is None:
                raise ProviderError("model_digest_missing", "Ollama model has no verifiable content digest")
            if model_digest != self.expected_model_digest:
                raise ProviderError("model_digest_mismatch", "installed Ollama model digest differs from the deployment lock")

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return only JSON matching the supplied schema. Model output is advisory and never authorizes side effects.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 512},
            }
            response = self.client.post(
                f"{self.base_url}/api/chat",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("model") != self.model:
                raise ProviderError("model_identity_mismatch", "Ollama returned an unexpected model")
            content = body.get("message", {}).get("content")
            if not isinstance(content, str) or not content:
                raise ProviderError("empty_model_output", "Ollama returned no structured content")
            try:
                output = json.loads(content)
            except json.JSONDecodeError:
                raise ProviderError("invalid_model_json", "Ollama response was not valid JSON") from None
            raw_digest = hashlib.sha256(response.content).hexdigest()
            provider_response_id = body.get("id")
            proxy_request_id = response.headers.get("X-OLA-Proxy-Request-ID")
            proxy_record_digest = response.headers.get("X-OLA-Proxy-Record-Digest")
            proxy_signature = response.headers.get("X-OLA-Proxy-Signature")
            proxy_key_id = response.headers.get("X-OLA-Proxy-Key-ID")
            if (
                not isinstance(proxy_request_id, str)
                or not proxy_request_id.startswith("ola-proxy:")
                or not isinstance(proxy_record_digest, str)
                or re.fullmatch(r"[a-f0-9]{64}", proxy_record_digest) is None
                or not isinstance(proxy_signature, str)
                or len(proxy_signature) != 88
                or not isinstance(proxy_key_id, str)
                or not proxy_key_id
            ):
                raise ProviderError("proxy_audit_missing", "Ollama response lacks signed independent proxy provenance")
            return {
                "data": output,
                "model": self.model,
                "model_digest": model_digest,
                "request_id": gateway_request_id,
                "request_id_source": "ola_gateway",
                "provider_response_id": provider_response_id if isinstance(provider_response_id, str) else None,
                "proxy_request_id": proxy_request_id,
                "proxy_record_digest": proxy_record_digest,
                "proxy_signature": proxy_signature,
                "proxy_key_id": proxy_key_id,
                "raw_response_digest": raw_digest,
                "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
            }
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ProviderError("ollama_request_failed", "Ollama request failed closed") from exc

    def close(self) -> None:
        self.client.close()
