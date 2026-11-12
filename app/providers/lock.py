"""Strict local provider lock loader. Model tags are never treated as immutable identities."""

import json
import os
import re
from pathlib import Path

from .contracts import ProviderError


_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def load_ollama_lock(path=None):
    configured_path = path or os.getenv("OLA_PROVIDER_LOCK_PATH")
    lock_path = Path(configured_path) if configured_path else (
        Path(__file__).resolve().parents[2] / "workstation" / "provider-lock.json"
    )
    try:
        raw = lock_path.read_bytes()
    except OSError:
        raise ProviderError("provider_lock_unavailable", "Ollama provider lock is unavailable") from None
    if len(raw) > 65536:
        raise ProviderError("provider_lock_too_large", "Ollama provider lock exceeds 64 KiB")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("provider_lock_invalid", "Ollama provider lock is invalid JSON") from None
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "providers"}:
        raise ProviderError("provider_lock_invalid", "Ollama provider lock has unknown fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ProviderError("provider_lock_version_unsupported", "Ollama provider lock version is unsupported")
    providers = payload["providers"]
    if not isinstance(providers, dict) or set(providers) != {"ollama"}:
        raise ProviderError("provider_lock_invalid", "Ollama provider lock must define only the ollama provider")
    entry = providers["ollama"]
    if not isinstance(entry, dict) or set(entry) != {"model", "model_digest"}:
        raise ProviderError("provider_lock_invalid", "Ollama provider lock entry has unknown fields")
    model = entry["model"]
    digest = entry["model_digest"]
    if not isinstance(model, str) or not model.strip():
        raise ProviderError("model_not_allowlisted", "Ollama model is not pinned in provider-lock.json")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ProviderError("model_digest_not_pinned", "Ollama model digest is not pinned in provider-lock.json")
    return model, digest
