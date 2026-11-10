"""Separate-process Ed25519 checkpoint signer with monotonic external state.

Run under a dedicated OS account. The supervisor must not have read access to
the private key or state directory. The signer only signs verified extensions
of its last signed checkpoint.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.igor_provenance_v3 import (
    CHECKPOINT_DOMAIN,
    GENESIS_HASH,
    canonical_bytes,
    checkpoint_payload,
    verify_event_chain,
    verify_signed_checkpoint,
)


def _checkpoint_hash(checkpoint):
    return hashlib.sha256(canonical_bytes(checkpoint)).hexdigest()


class CheckpointSigner:
    def __init__(self, private_key_path, state_path, *, signer_key_id="ola-local-checkpoint-key-v1"):
        self.private_key_path = Path(private_key_path)
        self.state_path = Path(state_path)
        self.signer_key_id = signer_key_id
        if os.name == "posix":
            mode = self.private_key_path.stat().st_mode & 0o777
            if mode & 0o077:
                raise PermissionError("checkpoint private key must be owner-only (0600)")
        key = serialization.load_pem_private_key(self.private_key_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("checkpoint signer requires an Ed25519 private key")
        self.private_key = key
        self.public_key = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, records, *, tenant_id):
        chain = verify_event_chain(records)
        if chain["status"] != "VERIFIED":
            raise ValueError(chain["reason"])
        if chain["tenant_id"] != tenant_id:
            raise ValueError("checkpoint_tenant_mismatch")

        previous_checkpoint_hash = GENESIS_HASH
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            previous = state["checkpoint"]
            if state.get("checkpoint_hash") != _checkpoint_hash(previous):
                raise ValueError("checkpoint_state_invalid")
            if records[previous["seq"]]["record_hash"] != previous["head_hash"]:
                raise ValueError("checkpoint_history_rewritten")
            previous_verification = verify_signed_checkpoint(
                records[: previous["seq"] + 1],
                previous,
                self.public_key,
            )
            if previous_verification["status"] != "VERIFIED":
                raise ValueError("checkpoint_state_invalid")
            if chain["seq"] <= previous["seq"]:
                raise ValueError("checkpoint_not_advanced")
            previous_checkpoint_hash = state["checkpoint_hash"]

        checkpoint = {
            "schema_version": 1,
            "domain": CHECKPOINT_DOMAIN,
            "tenant_id": tenant_id,
            "seq": chain["seq"],
            "head_hash": chain["head_hash"],
            "previous_checkpoint_hash": previous_checkpoint_hash,
            "issued_at": int(time.time()),
            "signer_key_id": self.signer_key_id,
        }
        signature = self.private_key.sign(canonical_bytes(checkpoint_payload(checkpoint)))
        checkpoint["signature"] = base64.b64encode(signature).decode("ascii")
        self._write_state({
            "checkpoint": checkpoint,
            "checkpoint_hash": _checkpoint_hash(checkpoint),
        })
        return checkpoint

    def _write_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="checkpoint-", suffix=".tmp", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(state, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--signer-key-id", default="ola-local-checkpoint-key-v1")
    args = parser.parse_args()
    request = json.load(sys.stdin)
    signer = CheckpointSigner(args.private_key, args.state_file, signer_key_id=args.signer_key_id)
    checkpoint = signer.sign(request["records"], tenant_id=request["tenant_id"])
    json.dump(checkpoint, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
