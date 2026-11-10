"""Out-of-process Ed25519 signer for OLA Agent Firewall evidence checkpoints."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socketserver
import stat
import tempfile
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.igor_agent_firewall import (
    CHECKPOINT_SCHEMA,
    GENESIS_HASH,
    canonical_json,
    checkpoint_manifest_bytes,
    checkpoint_sha256,
    verify_evidence_chain,
    verify_signed_checkpoint,
)


MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


class SignerError(ValueError):
    pass


class CheckpointSigner:
    """Private key and monotonic checkpoint state stay in this separate process."""

    def __init__(self, private_key_path, state_path, *, signer_key_id):
        self.private_key_path = Path(private_key_path)
        self.state_path = Path(state_path)
        self.signer_key_id = signer_key_id
        self._lock = threading.Lock()
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        if os.name == "posix":
            parent_info = self.state_path.parent.stat()
            if parent_info.st_uid != os.geteuid() or stat.S_IMODE(parent_info.st_mode) & 0o077:
                raise PermissionError("signer state directory must be owned by signer and mode 0700")
            info = self.private_key_path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise PermissionError("signer private key must be a regular non-symlink file")
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise PermissionError("signer private key must be owned by signer and mode 0600")
        key = serialization.load_pem_private_key(
            self.private_key_path.read_bytes(), password=None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("checkpoint signer requires an Ed25519 private key")
        self.private_key = key
        self.public_raw = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_sha256 = hashlib.sha256(self.public_raw).hexdigest()
        if not isinstance(signer_key_id, str) or not signer_key_id.strip():
            raise ValueError("signer_key_id is required")
        self._state = self._load_state()

    def _load_state(self):
        if not self.state_path.exists():
            return {"schema": 1, "tenants": {}}
        if self.state_path.is_symlink():
            raise SignerError("signer state must not be a symlink")
        info = self.state_path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise SignerError("signer state must be a regular non-symlink file")
        if os.name == "posix":
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise SignerError("signer state must be owned by signer and mode 0600")
        raw = self.state_path.read_bytes()
        if not raw or len(raw) > 16 * 1024 * 1024:
            raise SignerError("signer state is empty or too large")
        state = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        if canonical_json(state) + "\n" != raw.decode("utf-8"):
            raise SignerError("signer state is not canonical JSON")
        if not isinstance(state, dict) or state.get("schema") != 1 or not isinstance(state.get("tenants"), dict):
            raise SignerError("signer state schema is invalid")
        return state

    def sign(self, tenant_id, records):
        with self._lock:
            chain = verify_evidence_chain(records, expected_tenant_id=tenant_id)
            if chain["status"] != "VERIFIED":
                raise SignerError(chain["reason"])
            history = list(self._state["tenants"].get(tenant_id, []))
            if not isinstance(history, list):
                raise SignerError("signer checkpoint history is invalid")
            previous_checkpoint_sha256 = GENESIS_HASH
            previous_seq = -1
            if history:
                history_status = _verify_history(history, self.public_sha256, tenant_id)
                if history_status["status"] != "VERIFIED":
                    raise SignerError(history_status["reason"])
                previous = history[-1]
                previous_manifest = previous["manifest"]
                previous_seq = previous_manifest["seq"]
                if previous_seq >= len(records):
                    raise SignerError("checkpoint_history_rewritten")
                if records[previous_seq]["record_hash"] != previous_manifest["head_hash"]:
                    raise SignerError("checkpoint_history_rewritten")
                if chain["seq"] <= previous_seq:
                    raise SignerError("checkpoint_not_advanced")
                previous_checkpoint_sha256 = checkpoint_sha256(previous)

            manifest = {
                "schema": CHECKPOINT_SCHEMA,
                "tenant_id": tenant_id,
                "seq": chain["seq"],
                "head_hash": chain["head_hash"],
                "previous_checkpoint_sha256": previous_checkpoint_sha256,
                "issued_at": int(time.time()),
                "signer_key_id": self.signer_key_id,
            }
            manifest_bytes = checkpoint_manifest_bytes(manifest)
            signature = self.private_key.sign(manifest_bytes)
            checkpoint = {
                "manifest": manifest,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "signature": {
                    "algorithm": "Ed25519",
                    "key_id": self.signer_key_id,
                    "public_key_raw_b64": base64.b64encode(self.public_raw).decode("ascii"),
                    "public_key_sha256": self.public_sha256,
                    "value_b64": base64.b64encode(signature).decode("ascii"),
                },
            }
            next_state = {
                "schema": self._state["schema"],
                "tenants": dict(self._state["tenants"]),
            }
            next_state["tenants"][tenant_id] = history + [checkpoint]
            self._write_state(next_state)
            self._state = next_state
            return checkpoint

    def history(self, tenant_id):
        with self._lock:
            return list(self._state["tenants"].get(tenant_id, []))

    def _write_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = (canonical_json(state) + "\n").encode("utf-8")
        fd, temp_path = tempfile.mkstemp(
            prefix=".checkpoint-state-", suffix=".tmp", dir=self.state_path.parent
        )
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.state_path)
            if os.name == "posix":
                os.chmod(self.state_path, 0o600)
            directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise


def _verify_history(history, trusted_sha256, tenant_id):
    previous_hash = GENESIS_HASH
    previous_seq = -1
    for checkpoint in history:
        result = verify_signed_checkpoint(
            checkpoint, trusted_signer_sha256=trusted_sha256
        )
        if result["status"] != "VERIFIED":
            return result
        if result["tenant_id"] != tenant_id:
            return {"status": "BLOCKED", "reason": "checkpoint_tenant_mismatch"}
        if result["previous_checkpoint_sha256"] != previous_hash:
            return {"status": "BLOCKED", "reason": "checkpoint_link_mismatch"}
        if result["seq"] <= previous_seq:
            return {"status": "BLOCKED", "reason": "checkpoint_sequence_not_advanced"}
        previous_hash = result["checkpoint_sha256"]
        previous_seq = result["seq"]
    return {"status": "VERIFIED", "seq": previous_seq}


class _CheckpointHandler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
            self._respond({"status": "BLOCKED", "reason": "request_size_or_framing_invalid"})
            return
        try:
            request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
            if (
                not isinstance(request, dict)
                or set(request) != {"schema", "tenant_id", "records"}
                or request.get("schema") != "ola.agent-firewall.signer-request.v1"
            ):
                raise SignerError("request_schema_invalid")
            tenant_id = request.get("tenant_id")
            records = request.get("records")
            if not isinstance(tenant_id, str) or not tenant_id:
                raise SignerError("tenant_id_invalid")
            checkpoint = self.server.signer.sign(tenant_id, records)
            self._respond({
                "status": "SIGNED",
                "checkpoint": checkpoint,
                "history": self.server.signer.history(tenant_id),
            })
        except Exception as exc:
            reason = str(exc) if isinstance(exc, SignerError) else "signer_request_invalid"
            self._respond({"status": "BLOCKED", "reason": reason})

    def _respond(self, value):
        raw = (canonical_json(value) + "\n").encode("utf-8")
        if len(raw) <= MAX_RESPONSE_BYTES:
            self.wfile.write(raw)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON constant")


class CheckpointUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, socket_path, signer):
        self.signer = signer
        super().__init__(str(socket_path), _CheckpointHandler)


def serve(socket_path, signer):
    socket_path = Path(socket_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if socket_path.exists() or socket_path.is_symlink():
        info = socket_path.lstat()
        if not stat.S_ISSOCK(info.st_mode):
            raise RuntimeError("refusing to replace a non-socket signer path")
        socket_path.unlink()
    server = CheckpointUnixServer(socket_path, signer)
    os.chmod(socket_path, 0o660)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--socket", required=True)
    serve_parser.add_argument("--private-key", required=True)
    serve_parser.add_argument("--state-file", required=True)
    serve_parser.add_argument("--signer-key-id", default="ola-agent-firewall-checkpoint-v1")
    args = parser.parse_args()
    signer = CheckpointSigner(
        args.private_key, args.state_file, signer_key_id=args.signer_key_id
    )
    serve(args.socket, signer)


if __name__ == "__main__":
    main()
