"""Out-of-process Ollama audit proxy."""

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..canonical import canonical_json, digest_json, parse_json_object
from .lock import load_ollama_lock


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]


class OllamaAuditProxy:
    def __init__(
        self,
        *,
        private_key_path,
        audit_log_path,
        upstream_url="http://127.0.0.1:11434",
        lock_path=None,
        key_id="ola-ollama-proxy-v1",
        client=None,
        model_lock=None,
    ):
        parsed = urlsplit(upstream_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Ollama audit proxy upstream must be loopback-only HTTP")
        self.upstream_url = upstream_url.rstrip("/")
        self.model, self.model_digest = model_lock or load_ollama_lock(lock_path)
        self.audit_log_path = Path(audit_log_path)
        self.key_id = key_id
        self.client = client or httpx.Client(timeout=90, trust_env=False)

        key_path = Path(private_key_path)
        if os.name == "posix":
            mode = key_path.stat().st_mode & 0o777
            if mode & 0o077:
                raise PermissionError("Ollama proxy private key must be owner-only (0600)")
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Ollama proxy requires an Ed25519 private key")
        self.private_key = private_key
        self.public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def public_key_b64(self):
        return base64.b64encode(self.public_key).decode("ascii")

    def handle_tags(self):
        response = self.client.get(self.upstream_url + "/api/tags", timeout=10)
        return ProxyResponse(
            status_code=response.status_code,
            content=response.content,
            headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
        )

    def _installed_model_digest(self):
        response = self.client.get(self.upstream_url + "/api/tags", timeout=10)
        response.raise_for_status()
        body = response.json()
        models = body.get("models", [])
        match = next((item for item in models if item.get("name") == self.model), None)
        if match is None:
            raise ValueError("locked Ollama model is not installed")
        observed = match.get("digest")
        if observed != self.model_digest:
            raise ValueError("installed Ollama model digest differs from provider lock")
        return observed

    def _append_signed_record(self, record):
        record_digest = hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()
        signature = self.private_key.sign(canonical_json(record).encode("utf-8"))
        signed = {
            **record,
            "record_digest": record_digest,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
        line = (canonical_json(signed) + "\n").encode("utf-8")
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.audit_log_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            written = os.write(descriptor, line)
            if written != len(line):
                raise OSError("partial proxy audit log write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return record_digest, signed["signature"]

    def handle_chat(self, raw_body: bytes):
        if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > 65536:
            raise ValueError("Ollama proxy request is empty or exceeds 64 KiB")
        request = parse_json_object(raw_body.decode("utf-8"), max_bytes=65536)
        if request.get("model") != self.model:
            raise ValueError("Ollama proxy rejected a model outside the provider lock")
        model_digest = self._installed_model_digest()
        request_started_at = time.time()
        response = self.client.post(
            self.upstream_url + "/api/chat",
            content=raw_body,
            headers={"Content-Type": "application/json"},
            timeout=90,
        )
        response_received_at = time.time()
        response.raise_for_status()
        body = response.json()
        if body.get("model") != self.model:
            raise ValueError("Ollama response model identity mismatch")
        content = (body.get("message") or {}).get("content")
        if not isinstance(content, str) or not content:
            raise ValueError("Ollama returned no structured model content")

        output_status = "INVALID"
        tool_name = None
        tool_arguments_digest = None
        try:
            model_output = parse_json_object(content, max_bytes=32768)
            output_digest = digest_json(model_output)
            output_status = model_output.get("status", "INVALID")
            tool_name = model_output.get("tool_name")
            if output_status == "needs_tool":
                arguments = parse_json_object(model_output.get("tool_arguments_json"), max_bytes=16384)
                tool_arguments_digest = digest_json(arguments)
        except ValueError:
            output_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

        proxy_request_id = f"ola-proxy:{uuid.uuid4()}"
        record = {
            "domain": "OLA-OLLAMA-PROXY-RECORD-V1",
            "schema_version": 1,
            "key_id": self.key_id,
            "proxy_request_id": proxy_request_id,
            "model": self.model,
            "model_digest": model_digest,
            "request_digest": digest_json(request),
            "prompt_digest": digest_json(request.get("messages", request.get("prompt", ""))),
            "schema_digest": digest_json(request.get("format", {})),
            "raw_response_digest": hashlib.sha256(response.content).hexdigest(),
            "model_output_digest": output_digest,
            "output_status": output_status,
            "tool_name": tool_name,
            "tool_arguments_digest": tool_arguments_digest,
            "request_started_at": request_started_at,
            "response_received_at": response_received_at,
        }
        record_digest, signature = self._append_signed_record(record)
        return ProxyResponse(
            status_code=response.status_code,
            content=response.content,
            headers={
                "Content-Type": response.headers.get("Content-Type", "application/json"),
                "X-OLA-Proxy-Request-ID": proxy_request_id,
                "X-OLA-Proxy-Record-Digest": record_digest,
                "X-OLA-Proxy-Signature": signature,
                "X-OLA-Proxy-Key-ID": self.key_id,
            },
        )

    def close(self):
        self.client.close()
