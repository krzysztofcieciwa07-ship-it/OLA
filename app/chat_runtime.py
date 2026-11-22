import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx


SYSTEM_PROMPT = """You are NINA, a precise execution assistant.
Be useful, concise, and honest. Never claim an action was executed unless the execution endpoint returned VERIFIED evidence.
When a user asks for an action that requires execution, explain that the verified execution path is /nina-run.
"""


def _append_chat_evidence(tenant_id: str, record_type: str, payload: dict[str, Any]) -> str:
    # Import at call time to avoid the app.main <-> chat_runtime import cycle.
    from .main import append_record

    evidence = append_record(tenant_id, record_type, payload)
    evidence_id = evidence.get("id") if isinstance(evidence, dict) else None
    if not isinstance(evidence_id, str) or not evidence_id:
        raise RuntimeError("NINA chat Evidence append returned no record id")
    return evidence_id


def _openai_endpoint() -> str:
    """Return a validated HTTPS endpoint using the shared OLA host/port allowlist."""
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    try:
        parsed_url = urlsplit(base_url)
        endpoint_host = (parsed_url.hostname or "").rstrip(".").lower()
        endpoint_port = parsed_url.port if parsed_url.port is not None else 443
        if endpoint_port < 1:
            raise RuntimeError("OPENAI_BASE_URL is not an approved HTTPS LLM endpoint")
    except ValueError:
        raise RuntimeError("OPENAI_BASE_URL is not an approved HTTPS LLM endpoint") from None

    allowed_hosts = {
        host.strip().lower().rstrip(".")
        for host in os.getenv("OLA_LLM_ALLOWED_HOSTS", "api.openai.com").split(",")
        if host.strip()
    }
    endpoint_host_port = (
        f"[{endpoint_host}]:{endpoint_port}"
        if ":" in endpoint_host else f"{endpoint_host}:{endpoint_port}"
    )
    host_allowlisted = endpoint_host in allowed_hosts and endpoint_port == 443
    host_port_allowlisted = endpoint_host_port in allowed_hosts
    if (
        parsed_url.scheme != "https"
        or not endpoint_host
        or not (host_allowlisted or host_port_allowlisted)
        or parsed_url.username
        or parsed_url.password
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise RuntimeError("OPENAI_BASE_URL is not an approved HTTPS LLM endpoint")
    return base_url + "/responses"


def chat(tenant_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("NINA_CHAT_MODEL", os.getenv("OLA_LLM_MODEL", "gpt-5.6-luna"))

    def blocked(reason: str, message: str | None = None) -> dict[str, Any]:
        # Every returned denial is a tenant-scoped decision with trusted Evidence.
        # Evidence append failure propagates: a BLOCK without its audit record
        # is not a completed response.
        evidence_id = _append_chat_evidence(tenant_id, "decision.chat", {
            "decision": "BLOCK",
            "reason": reason,
            "model": model,
            "message_count": len(messages),
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        result: dict[str, Any] = {
            "status": "BLOCK",
            "reason": reason,
            "evidence_id": evidence_id,
        }
        if message is not None:
            result["message"] = message
        return result

    if not api_key:
        return blocked(
            "OPENAI_API_KEY is not configured",
            "NINA conversational LLM access is not configured yet.",
        )

    try:
        endpoint = _openai_endpoint()
    except RuntimeError as exc:
        return blocked(str(exc))

    payload = {
        "model": model,
        "input": [{"role": "system", "content": SYSTEM_PROMPT}] + messages[-20:],
    }
    try:
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
            follow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            return blocked("LLM request redirected")
        response.raise_for_status()
        data = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        return blocked(f"LLM request failed: {exc.__class__.__name__}")
    except (ValueError, TypeError, RecursionError):
        return blocked("LLM returned invalid JSON")

    if not isinstance(data, dict):
        return blocked("LLM returned invalid response")

    text = data.get("output_text")
    if text is not None and not isinstance(text, str):
        return blocked("LLM returned invalid response")

    if not text:
        output = data.get("output", [])
        if not isinstance(output, list):
            return blocked("LLM returned invalid response")
        for item in output:
            if not isinstance(item, dict):
                return blocked("LLM returned invalid response")
            content = item.get("content", [])
            if not isinstance(content, list):
                return blocked("LLM returned invalid response")
            for part in content:
                if not isinstance(part, dict):
                    return blocked("LLM returned invalid response")
                if part.get("type") == "output_text":
                    candidate = part.get("text")
                    if not isinstance(candidate, str):
                        return blocked("LLM returned invalid response")
                    text = candidate
                    break
            if text:
                break

    if not text:
        return blocked("LLM returned no output")

    evidence_id = _append_chat_evidence(tenant_id, "chat.completed", {
        "model": model,
        "message_count": len(messages),
        "response_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "status": "COMPLETED_UNVERIFIED",
        "verified": False,
        "message": text,
        "model": model,
        "evidence_id": evidence_id,
    }
