"""REAL AURORA browser -> HTTP FastAPI -> local Ollama -> tenant Evidence.

Runs ONLY as part of CI alongside a live ollama model and an OLA Docker
container named ola-ollama-e2e exposing :8000 on the runner loopback.
Does not mock fetch, chat or any other HTTP handler; no production claims.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
CONTAINER = "ola-ollama-e2e"
OUT = Path(os.getenv("AURORA_EVIDENCE_DIR", "aurora-live-ollama-evidence"))


def provision_disposable_ci_operator() -> tuple[str, str]:
    # This is an isolated CI container and uses the already configured CI-only
    # pepper; raw credential stays only in process memory and is never logged.
    script = """
import json
import uuid
from scripts.provision_local_operator import issue_operator_key
tenant_id, key = issue_operator_key("ci-browser-" + uuid.uuid4().hex)
print(json.dumps({"tenant_id":tenant_id, "key":key}))
"""
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    return value["tenant_id"], value["key"]


def run() -> None:
    tenant_id, key = provision_disposable_ci_operator()
    OUT.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=BASE, timeout=12, follow_redirects=False, trust_env=False) as api:
        health = api.get("/health")
        assert health.status_code == 200 and health.json().get("status") == "ok"

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            chat_requests = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("request", lambda req: chat_requests.append((req.method, req.url)) if req.url.endswith("/chat") else None)
            page.set_default_timeout(90000)
            page.goto(BASE + "/", wait_until="domcontentloaded")
            assert "OLA di OS" in page.content()
            page.locator("#healthStatus").get_by_text("ONLINE").wait_for()

            page.locator('[data-view="settings"]').first.click()
            page.locator("#apiKey").fill(key)
            page.locator("#verifyApiKey").click()
            page.locator("#keyState").get_by_text("UWIERZYTELNIONY").wait_for()

            page.locator('[data-view="chat"]').first.click()
            page.locator("#chatInput").fill("Odpowiedz jednym krótkim zdaniem po polsku.")
            page.locator("#chatSend").click()
            # A local response is not enough: the HTTP+Evidence readback below
            # additionally proves it came from the real Ollama transport.
            page.locator("#chatMessages .message.assistant").last.wait_for()
            visible = page.locator("#chatMessages .message.assistant").last.text_content()
            assert visible.startswith("NINA: ") and len(visible.strip()) > len("NINA: ")
            assert not errors, errors
            assert any(method == "POST" and url == BASE + "/chat" for method, url in chat_requests)

            # The UI must not serialize the session credential into rendered chat.
            assert key not in page.locator("#chatMessages").inner_text()
            page.screenshot(path=str(OUT / "aurora-live-ollama.png"), animations="disabled")
            browser.close()

        headers = {"X-API-Key": key}
        session = api.get("/auth/session", headers=headers)
        assert session.status_code == 200 and session.json()["tenant_id"] == tenant_id

        overview = api.get("/control/overview", headers=headers)
        assert overview.status_code == 200, overview.text
        body = overview.json()
        assert body.get("tenant_id") == tenant_id
        recent = [event for event in body.get("recent_events", []) if event.get("type") == "chat.completed"]
        assert len(recent) == 1, body
        record_id = recent[0]["record_id"]
        proof = api.get("/evidence/" + record_id, headers=headers)
        assert proof.status_code == 200, proof.text
        data = proof.json()
        evidence = data["payload"]
        assert data["tenant_id"] == tenant_id
        assert data["record_type"] == "chat.completed"
        assert evidence["provider"] == "ollama"
        assert evidence["model"] == os.environ.get("OLA_LLM_MODEL", "qwen2.5:0.5b-instruct")
        assert evidence["scope"] == "CHAT_ONLY"
        # UI-rendered text includes the prefixed role ("NINA: ").
        output = visible[len("NINA: "):]
        assert evidence["response_digest"] == hashlib.sha256(output.encode("utf-8")).hexdigest()

        invalid = api.get("/control/overview", headers={"X-API-Key": "not-a-valid-key"})
        assert invalid.status_code == 401

    result = {
        "status": "LOCAL_CI_E2E_PASS",
        "source_sha": os.getenv("SOURCE_SHA", "UNKNOWN"),
        "surface": "REAL_BROWSER_REAL_HTTP_REAL_OLLAMA",
        "provider": "ollama",
        "model": evidence["model"],
        "evidence_record_sha256": data["record_hash"],
        "checks": ["AUTHENTICATED_BROWSER", "REAL_CHAT_HTTP", "OLLAMA_PROVENANCE",
                   "RENDERED_TEXT_DIGEST_MATCH", "EVIDENCE_READBACK", "WRONG_KEY_401"],
        "production": "NO-GO",
        "zbook_physical": "NOT_TESTED",
    }
    (OUT / "proof.json").write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    run()
