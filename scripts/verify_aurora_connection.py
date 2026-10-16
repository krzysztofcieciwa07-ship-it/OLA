"""Fail-closed live check: AURORA page -> OLA API -> Ollama -> tenant evidence.

For an ALREADY STARTED local preview:
    python scripts/verify_aurora_connection.py
    python scripts/verify_aurora_connection.py --health-only

No remote hosts, redirect following, shell execution, or production approval.
Prompts for the operator API key without storing it or putting it on the CLI.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import sys
from urllib.parse import urlsplit

import httpx

REQUIRED_ROUTES = {
    ("/health", "get"),
    ("/auth/session", "get"),
    ("/chat", "post"),
    ("/nina-run", "post"),
    ("/control/overview", "get"),
    ("/evidence/{record_id}", "get"),
}


class ConnectionBlocked(RuntimeError):
    pass


def check_local_origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not parsed.port
        or not (1024 <= parsed.port <= 65535)
    ):
        raise ConnectionBlocked("only loopback HTTP origins with an explicit port are allowed")
    return url.rstrip("/")


def checked_json(client: httpx.Client, method: str, path: str, *, key: str | None = None, data=None):
    headers = {"Accept": "application/json"}
    if key is not None:
        headers["X-API-Key"] = key
    response = client.request(method, path, headers=headers, json=data)
    if response.status_code != 200:
        raise ConnectionBlocked(f"{path}: HTTP {response.status_code}")
    try:
        value = response.json()
    except (ValueError, TypeError) as exc:
        raise ConnectionBlocked(f"{path}: non-JSON response") from exc
    if not isinstance(value, dict):
        raise ConnectionBlocked(f"{path}: expected object")
    return value


def probe(client: httpx.Client, key: str | None, *, health_only: bool = False) -> dict:
    result = {"status": "BLOCKED", "production": "NO-GO", "checks": []}
    health = checked_json(client, "GET", "/health")
    if health.get("status") != "ok":
        raise ConnectionBlocked("OLA /health is not ok")
    result["checks"].append("API_HEALTH_OK")

    spec = checked_json(client, "GET", "/openapi.json")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise ConnectionBlocked("OpenAPI paths missing")
    if any(method not in paths.get(path, {}) for path, method in REQUIRED_ROUTES):
        raise ConnectionBlocked("not the expected OLA runtime API (required routes missing)")
    result["checks"].append("OLA_ROUTES_PRESENT")
    if health_only:
        result["status"] = "API_PRESENT_AUTH_AND_LLM_UNTESTED"
        return result
    if not key:
        raise ConnectionBlocked("operator API key required")

    operator = checked_json(client, "GET", "/auth/session", key=key)
    if operator.get("authenticated") is not True or not operator.get("tenant_id"):
        raise ConnectionBlocked("operator is not authenticated")
    tenant = operator["tenant_id"]
    result["checks"].append("TENANT_AUTHENTICATED")

    overview = checked_json(client, "GET", "/control/overview", key=key)
    if overview.get("tenant_id") != tenant or overview.get("schema") != "ola.command-center.v1":
        raise ConnectionBlocked("control plane tenant or schema mismatch")
    result["checks"].append("TENANT_CONTROL_CONNECTED")

    response = checked_json(
        client, "POST", "/chat", key=key,
        data={"messages": [{"role": "user", "content": "Reply with a short confirmation."}]},
    )
    if not (
        response.get("status") == "VERIFIED"
        and response.get("scope") == "CHAT_ONLY"
        and response.get("provider") == "ollama"
        and isinstance(response.get("message"), str)
        and response["message"].strip()
        and isinstance(response.get("evidence_id"), str)
        and response["evidence_id"]
    ):
        raise ConnectionBlocked("NINA chat provider not confirmed as live Ollama")
    digest = hashlib.sha256(response["message"].encode("utf-8")).hexdigest()
    if digest != response.get("response_digest"):
        raise ConnectionBlocked("chat response digest mismatch")
    result["checks"].append("OLLAMA_RESPONSE_RECEIVED")

    evidence = checked_json(client, "GET", "/evidence/" + response["evidence_id"], key=key)
    payload = evidence.get("payload", {})
    if not (
        evidence.get("tenant_id") == tenant
        and evidence.get("record_type") == "chat.completed"
        and isinstance(payload, dict)
        and payload.get("response_digest") == digest
        and payload.get("provider") == "ollama"
        and payload.get("scope") == "CHAT_ONLY"
    ):
        raise ConnectionBlocked("chat evidence missing or mismatched")
    result["checks"].append("TENANT_EVIDENCE_READBACK_OK")
    result["status"] = "LOCAL_CHAT_API_ENGINE_CONNECTED"
    result["provider"] = "ollama"
    result["model"] = response.get("model")
    result["tenant_id"] = tenant
    result["evidence_id"] = response["evidence_id"]
    result["execution"] = "NOT_RUN"
    result["igor_independent"] = "NOT_TESTED"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        base = check_local_origin(args.base_url)
        key = None if args.health_only else getpass.getpass("OLA operator X-API-Key: ")
        with httpx.Client(base_url=base, timeout=65.0, trust_env=False, follow_redirects=False) as client:
            result = probe(client, key, health_only=args.health_only)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ConnectionBlocked, httpx.HTTPError, ValueError, EOFError, KeyboardInterrupt) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "production": "NO-GO",
            "reason": type(exc).__name__ if not isinstance(exc, ConnectionBlocked) else str(exc),
        }, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
