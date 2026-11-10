"""Gateway-side client for the separately running checkpoint signer."""

from __future__ import annotations

import os
import socket

from scripts.igor_agent_firewall import (
    canonical_json,
    strict_json_loads,
    verify_checkpoint_chain,
    verify_signed_checkpoint,
)


MAX_SIGNER_REQUEST_BYTES = 8 * 1024 * 1024
MAX_SIGNER_RESPONSE_BYTES = 1024 * 1024


class SignerUnavailable(RuntimeError):
    pass


class UnixCheckpointSignerClient:
    def __init__(self, socket_path: str, trusted_signer_sha256: str, *, timeout_s: float = 5.0):
        self.socket_path = socket_path
        self.trusted_signer_sha256 = trusted_signer_sha256
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls):
        socket_path = os.getenv("OLA_FIREWALL_SIGNER_SOCKET", "").strip()
        fingerprint = os.getenv("OLA_FIREWALL_SIGNER_PUBLIC_KEY_SHA256", "").strip()
        if not socket_path or not fingerprint:
            raise SignerUnavailable("checkpoint signer is not configured")
        return cls(socket_path, fingerprint)

    def sign(self, tenant_id: str, records: list[dict]) -> dict:
        request = {
            "schema": "ola.agent-firewall.signer-request.v1",
            "tenant_id": tenant_id,
            "records": records,
        }
        raw = (canonical_json(request) + "\n").encode("utf-8")
        if len(raw) > MAX_SIGNER_REQUEST_BYTES:
            raise SignerUnavailable("evidence chain exceeds signer request limit")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout_s)
                client.connect(self.socket_path)
                client.sendall(raw)
                chunks = bytearray()
                while len(chunks) <= MAX_SIGNER_RESPONSE_BYTES:
                    part = client.recv(min(65536, MAX_SIGNER_RESPONSE_BYTES + 1 - len(chunks)))
                    if not part:
                        break
                    chunks.extend(part)
                    if b"\n" in part:
                        break
            if not chunks or len(chunks) > MAX_SIGNER_RESPONSE_BYTES or not chunks.endswith(b"\n"):
                raise SignerUnavailable("checkpoint signer returned an invalid response frame")
            response = strict_json_loads(chunks[:-1].decode("utf-8"))
            if not isinstance(response, dict) or response.get("status") != "SIGNED":
                raise SignerUnavailable("checkpoint signer blocked the request")
            checkpoint = response.get("checkpoint")
            history = response.get("history")
            verified = verify_signed_checkpoint(
                checkpoint,
                trusted_signer_sha256=self.trusted_signer_sha256,
            )
            history_verified = verify_checkpoint_chain(
                history, trusted_signer_sha256=self.trusted_signer_sha256
            )
            if (
                verified.get("status") != "VERIFIED"
                or verified.get("tenant_id") != tenant_id
                or history_verified.get("status") != "VERIFIED"
                or history_verified.get("checkpoint_sha256") != verified.get("checkpoint_sha256")
            ):
                raise SignerUnavailable("checkpoint signature, history, or tenant binding is invalid")
            return {"checkpoint": checkpoint, "history": history}
        except (OSError, TimeoutError, ValueError, UnicodeError) as exc:
            if isinstance(exc, SignerUnavailable):
                raise
            raise SignerUnavailable("checkpoint signer is unavailable") from None
