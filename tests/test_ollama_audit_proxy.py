import base64
import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.canonical import canonical_json, digest_json
from app.providers.ollama_audit_proxy import OllamaAuditProxy


MODEL = "qwen2.5:0.5b-instruct"
MODEL_DIGEST = "sha256:" + "a" * 64


def _key_file(path):
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    path.chmod(0o600)
    return key


def _client(output, *, observed_digest=MODEL_DIGEST):
    response_content = json.dumps({
        "model": MODEL,
        "id": "ollama-no-response-id",
        "message": {"content": json.dumps(output)},
    }).encode("utf-8")

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={
                "models": [{"name": MODEL, "digest": observed_digest}],
            })
        if request.url.path == "/api/chat":
            return httpx.Response(200, content=response_content, headers={"Content-Type": "application/json"})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _request():
    return json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Calculate 17 times 23."},
        ],
        "stream": False,
        "format": {"type": "object", "properties": {"status": {"type": "string"}}},
        "options": {"temperature": 0},
    }).encode("utf-8")


def test_proxy_signs_model_output_and_capability_argument_digests(tmp_path):
    key_path = tmp_path / "ollama-proxy.pem"
    audit_path = tmp_path / "ollama-proxy.jsonl"
    private_key = _key_file(key_path)
    output = {
        "status": "needs_tool",
        "summary": "Evaluate the expression.",
        "reasoning": "A bounded arithmetic tool is sufficient.",
        "tool_name": "tool.safe_expression",
        "tool_arguments_json": '{"expression":"17 * 23"}',
        "evidence_refs": [],
    }
    proxy = OllamaAuditProxy(
        private_key_path=key_path,
        audit_log_path=audit_path,
        model_lock=(MODEL, MODEL_DIGEST),
        client=_client(output),
    )

    response = proxy.handle_chat(_request())

    assert response.status_code == 200
    assert response.headers["X-OLA-Proxy-Request-ID"].startswith("ola-proxy:")
    signed = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    signature = base64.b64decode(signed.pop("signature"))
    record_digest = signed.pop("record_digest")
    assert record_digest == hashlib.sha256(canonical_json(signed).encode("utf-8")).hexdigest()
    private_key.public_key().verify(signature, canonical_json(signed).encode("utf-8"))
    assert signed["model_digest"] == MODEL_DIGEST
    assert signed["model_output_digest"] == digest_json(output)
    assert signed["tool_name"] == "tool.safe_expression"
    assert signed["tool_arguments_digest"] == digest_json({"expression": "17 * 23"})
    assert response.headers["X-OLA-Proxy-Record-Digest"] == record_digest


def test_proxy_blocks_model_digest_drift_before_calling_chat(tmp_path):
    key_path = tmp_path / "ollama-proxy.pem"
    audit_path = tmp_path / "ollama-proxy.jsonl"
    _key_file(key_path)
    client = _client({
        "status": "complete", "summary": "No tool.", "reasoning": "Done.",
        "tool_name": None, "tool_arguments_json": "", "evidence_refs": [],
    }, observed_digest="sha256:" + "b" * 64)
    proxy = OllamaAuditProxy(
        private_key_path=key_path,
        audit_log_path=audit_path,
        model_lock=(MODEL, MODEL_DIGEST),
        client=client,
    )

    with pytest.raises(ValueError, match="digest differs"):
        proxy.handle_chat(_request())

    assert not audit_path.exists()


def test_proxy_rejects_non_loopback_upstream(tmp_path):
    key_path = tmp_path / "ollama-proxy.pem"
    _key_file(key_path)
    with pytest.raises(ValueError, match="loopback-only"):
        OllamaAuditProxy(
            private_key_path=key_path,
            audit_log_path=tmp_path / "audit.jsonl",
            upstream_url="http://192.0.2.10:11434",
            model_lock=(MODEL, MODEL_DIGEST),
            client=_client({}),
        )
