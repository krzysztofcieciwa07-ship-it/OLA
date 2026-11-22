import hashlib
import http.client
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any


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


def chat(tenant_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("NINA_CHAT_MODEL", os.getenv("OLA_LLM_MODEL", "gpt-5.6-luna"))

    def blocked(reason: str, message: str | None = None) -> dict[str, Any]:
        # Every returned denial is an authenticated, tenant-scoped decision.
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

    payload = {
        "model": model,
        "input": [{"role": "system", "content": SYSTEM_PROMPT}] + messages[-20:],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.load(response)
    except (OSError, http.client.IncompleteRead) as exc:
        return blocked(f"LLM request failed: {exc.__class__.__name__}")
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, TypeError):
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
