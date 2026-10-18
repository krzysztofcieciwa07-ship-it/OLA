"""Contract tests for real AURORA/Core/Ollama connection verifier (mock transport)."""
import hashlib

import httpx
import pytest

from scripts.verify_aurora_connection import (
    REQUIRED_ROUTES,
    ConnectionBlocked,
    check_local_origin,
    probe,
)

TENANT = "tenant-test"
TEXT = "OLA is connected."
DIGEST = hashlib.sha256(TEXT.encode()).hexdigest()
EVIDENCE_ID = "record-test-123"


def response_for(request, *, provider="ollama", evidence_ok=True, tenant_ok=True, fail_chat=False):
    path = request.url.path
    key = request.headers.get("X-API-Key")
    if path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/openapi.json":
        return httpx.Response(200, json={"paths": {p: {m: {}} for p, m in REQUIRED_ROUTES}})
    if key != "operator-secret":
        return httpx.Response(401, json={"detail": "invalid API key"})
    if path == "/auth/session":
        return httpx.Response(200, json={"authenticated": True, "tenant_id": TENANT})
    if path == "/control/overview":
        return httpx.Response(200, json={"tenant_id": TENANT if tenant_ok else "someone-else", "schema": "ola.command-center.v1"})
    if path == "/chat":
        assert request.method == "POST"
        return httpx.Response(200, json={
            "status": "BLOCK" if fail_chat else "VERIFIED",
            "scope": "CHAT_ONLY",
            "provider": provider,
            "message": TEXT,
            "response_digest": DIGEST,
            "evidence_id": EVIDENCE_ID,
            "model": "local-test-model",
        })
    if path == "/evidence/" + EVIDENCE_ID:
        return httpx.Response(200, json={
            "tenant_id": TENANT,
            "record_type": "chat.completed",
            "payload": {"response_digest": DIGEST if evidence_ok else "bad", "provider": provider, "scope": "CHAT_ONLY"},
        })
    return httpx.Response(404)


def fake_client(**options):
    return httpx.Client(
        base_url="http://127.0.0.1:18081",
        transport=httpx.MockTransport(lambda request: response_for(request, **options)),
        follow_redirects=False,
        trust_env=False,
    )


def test_connected_requires_actual_response_and_matching_evidence():
    with fake_client() as client:
        value = probe(client, "operator-secret")
    assert value["status"] == "LOCAL_CHAT_API_ENGINE_CONNECTED"
    assert value["production"] == "NO-GO"
    assert value["execution"] == "NOT_RUN"
    assert value["igor_independent"] == "NOT_TESTED"
    assert value["checks"] == [
        "API_HEALTH_OK", "OLA_ROUTES_PRESENT", "TENANT_AUTHENTICATED",
        "TENANT_CONTROL_CONNECTED", "OLLAMA_RESPONSE_RECEIVED",
        "TENANT_EVIDENCE_READBACK_OK",
    ]


def test_health_only_does_not_contact_protected_api_or_llm():
    with fake_client() as client:
        value = probe(client, None, health_only=True)
    assert value["status"] == "API_PRESENT_AUTH_AND_LLM_UNTESTED"
    assert value["checks"] == ["API_HEALTH_OK", "OLA_ROUTES_PRESENT"]


@pytest.mark.parametrize("variation", [
    {"provider": "openai"},
    {"evidence_ok": False},
    {"tenant_ok": False},
    {"fail_chat": True},
])
def test_unknown_or_mismatched_components_never_claim_connection(variation):
    with fake_client(**variation) as client:
        with pytest.raises(ConnectionBlocked):
            probe(client, "operator-secret")


def test_invalid_key_never_claims_connected():
    with fake_client() as client:
        with pytest.raises(ConnectionBlocked, match="HTTP 401"):
            probe(client, "wrong-key")


@pytest.mark.parametrize("url", [
    "file:///C:/preview/index.html",
    "https://127.0.0.1:18081",
    "http://somewhere.example:18081",
    "http://127.0.0.1:18081/other",
    "http://127.0.0.1:18081/?evil=1",
    "http://user:password@127.0.0.1:18081",
    "http://127.0.0.1",
])
def test_secrets_cannot_be_sent_to_nonlocal_endpoint(url):
    with pytest.raises(ConnectionBlocked):
        check_local_origin(url)
