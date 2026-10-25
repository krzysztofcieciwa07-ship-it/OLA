"""Explicitly opted-in Hugging Face inference adapter for OLA.

This module is shared by the NINA chat surface and the agent pipeline.
Secrets and raw prompts are not written to the evidence chain here.
"""

import os

import httpx


ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
DEFAULT_MODEL = "zai-org/GLM-5.3:novita"


def invoke_huggingface_chat(*, model: str, messages: list[dict], timeout: float) -> dict:
    """Call a single approved cloud model; fail closed on misconfiguration/errors."""
    if os.getenv("OLA_HF_ALLOW_CLOUD") != "1":
        raise RuntimeError("Hugging Face cloud inference requires OLA_HF_ALLOW_CLOUD=1")

    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN is not configured in the OLA runtime")

    approved = {name.strip() for name in os.getenv("OLA_HF_MODELS", DEFAULT_MODEL).split(",") if name.strip()}
    if not model or model not in approved:
        raise RuntimeError("Hugging Face model is not on the approved allowlist")

    raw_budget = os.getenv("OLA_HF_MAX_TOKENS", "512")
    if not raw_budget.isascii() or not raw_budget.isdecimal() or not 1 <= int(raw_budget) <= 2048:
        raise RuntimeError("OLA_HF_MAX_TOKENS must be an integer from 1 to 2048")
    if not messages or not all(isinstance(m, dict) and m.get("role") in {"system", "user", "assistant"}
                               and isinstance(m.get("content"), str) for m in messages):
        raise RuntimeError("Invalid Hugging Face chat messages")

    try:
        response = httpx.post(
            ROUTER_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": int(raw_budget), "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Never echo request headers, tokens, or provider response bodies into logs.
        raise RuntimeError(f"Hugging Face inference failed: {type(exc).__name__}") from None

    choices = result.get("choices") if isinstance(result, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("Hugging Face returned an invalid completion")
    message = choices[0].get("message")
    output = message.get("content") if isinstance(message, dict) else None
    if not isinstance(output, str) or not output.strip():
        raise RuntimeError("Hugging Face returned an empty completion")
    response_id = result.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise RuntimeError("Hugging Face returned no response ID")

    return {"output": output, "response_id": response_id, "model": model, "usage": result.get("usage")}
