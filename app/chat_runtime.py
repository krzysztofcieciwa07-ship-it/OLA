import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any

SYSTEM_PROMPT = """You are NINA, a precise execution assistant.
Be useful, concise, and honest. Never claim an action was executed unless the execution endpoint returned VERIFIED evidence.
When a user asks for an action that requires execution, explain that the verified execution path is /nina-run.
"""

def chat(tenant_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("NINA_CHAT_MODEL", os.getenv("OLA_LLM_MODEL", "gpt-5.6-luna"))
    if not api_key:
        return {"status": "BLOCK", "reason": "OPENAI_API_KEY is not configured", "message": "NINA conversational LLM access is not configured yet."}
    payload = {"model": model, "input": [{"role": "system", "content": SYSTEM_PROMPT}] + messages[-20:]}
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return {"status": "BLOCK", "reason": f"LLM request failed: {exc.__class__.__name__}"}
    text = data.get("output_text")
    if not text:
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text = part.get("text"); break
            if text: break
    if not text:
        return {"status": "BLOCK", "reason": "LLM returned no output"}
    from .main import append_record
    append_record(tenant_id, "chat.completed", {"model": model, "message_count": len(messages), "response_digest": hashlib.sha256(text.encode()).hexdigest()})
    return {"status": "VERIFIED", "message": text, "model": model}
