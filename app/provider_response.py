"""Validate provider envelopes before chat evidence or agent tools can run."""
from __future__ import annotations

import hashlib
from typing import Any

from .hashchain import canonical_json


def parse_provider_response(provider: str, body: Any) -> tuple[str, str]:
    """Return text and identity, or a payload-free ValueError on malformed data."""
    if not isinstance(body, dict):
        raise ValueError("provider response must be an object")

    if provider == "ollama":
        message = body.get("message")
        if not isinstance(message, dict):
            raise ValueError("provider message must be an object")
        output = message.get("content")
        response_id = body.get("id")
        # Standard Ollama responses have no server-assigned id. Preserve the
        # existing content-addressed identity, without coercing a malformed id.
        if response_id is None:
            response_id = "ollama:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    elif provider == "openai":
        output = body.get("output_text")
        if output is not None and not isinstance(output, str):
            raise ValueError("provider output text must be a string")
        if not output:
            items = body.get("output", [])
            if not isinstance(items, list):
                raise ValueError("provider output must be a list")
            fragments = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("provider output item must be an object")
                # Reasoning and other non-text items can legitimately omit
                # content. Explicit null and malformed content are rejected.
                content = item.get("content", [])
                if not isinstance(content, list):
                    raise ValueError("provider content must be a list")
                for part in content:
                    if not isinstance(part, dict):
                        raise ValueError("provider content part must be an object")
                    if part.get("type") in ("output_text", "text"):
                        text = part.get("text")
                        if not isinstance(text, str):
                            raise ValueError("provider text part must be a string")
                        fragments.append(text)
            output = "\n".join(fragments)
        response_id = body.get("id")
    else:
        raise ValueError("unsupported provider response")

    if not isinstance(output, str) or not output.strip():
        raise ValueError("provider returned empty or invalid text")
    if not isinstance(response_id, str) or not response_id.strip():
        raise ValueError("provider returned an invalid response identity")
    return output, response_id
