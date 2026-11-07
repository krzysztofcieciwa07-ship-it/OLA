#!/usr/bin/env python3
"""Offline verification of an OLA customer evidence ZIP."""
import argparse
import base64
import json
import sys
import subprocess
import tempfile
from pathlib import Path

from app.customer_bundle.verifier import verify_customer_bundle


def _read_trust_store(path: Path) -> tuple[dict[str, bytes], set[str], dict | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("trust store is unreadable or invalid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
        raise ValueError("trust store must contain a keys object")
    trusted = {}
    for key_id, raw in data["keys"].items():
        if not isinstance(key_id, str) or not key_id or not isinstance(raw, str):
            raise ValueError("trust store key entries must map key IDs to base64url public keys")
        try:
            padded = raw + "=" * (-len(raw) % 4)
            public_key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (ValueError, UnicodeEncodeError, base64.binascii.Error) as exc:
            raise ValueError(f"invalid public key encoding for {key_id}") from exc
        if len(public_key) != 32:
            raise ValueError(f"Ed25519 public key {key_id} must decode to exactly 32 bytes")
        trusted[key_id] = public_key
    revoked = data.get("revoked_key_ids", [])
    if not isinstance(revoked, list) or any(not isinstance(value, str) for value in revoked):
        raise ValueError("revoked_key_ids must be a list of key IDs")
    timestamp = data.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, dict):
        raise ValueError("timestamp trust settings must be an object")
    return trusted, set(revoked), timestamp


def _timestamp_verifier(config: dict | None, trust_store_dir: Path):
    if not isinstance(config, dict):
        return None
    ca_value = config.get("ca_file")
    untrusted_value = config.get("untrusted_file")
    if not isinstance(ca_value, str) or not ca_value:
        return None
    ca_file = (trust_store_dir / ca_value).resolve() if not Path(ca_value).is_absolute() else Path(ca_value)
    if not ca_file.is_file():
        return None
    untrusted_file = None
    if untrusted_value is not None:
        if not isinstance(untrusted_value, str) or not untrusted_value:
            return None
        untrusted_file = (trust_store_dir / untrusted_value).resolve() if not Path(untrusted_value).is_absolute() else Path(untrusted_value)
        if not untrusted_file.is_file():
            return None

    def verify(token: bytes, manifest_bytes: bytes, signed_at: int) -> bool:
        if not isinstance(token, bytes) or not token or not isinstance(manifest_bytes, bytes):
            return False
        if type(signed_at) is not int:
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="ola-ts-verify-") as temporary:
                root = Path(temporary)
                manifest_path = root / "manifest.json"
                token_path = root / "timestamp.tsr"
                manifest_path.write_bytes(manifest_bytes)
                token_path.write_bytes(token)
                command = [
                    "openssl", "ts", "-verify",
                    "-data", str(manifest_path),
                    "-in", str(token_path),
                    "-CAfile", str(ca_file),
                ]
                if untrusted_file is not None:
                    command.extend(["-untrusted", str(untrusted_file)])
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=20,
                )
                return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    return verify


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a dual-signed OLA customer evidence bundle offline.")
    parser.add_argument("bundle", type=Path, help="Customer evidence ZIP")
    parser.add_argument("--trust-store", required=True, type=Path, help="Out-of-band trusted Ed25519 public key JSON")
    args = parser.parse_args()

    try:
        trusted, revoked, timestamp_config = _read_trust_store(args.trust_store)
        timestamp_verifier = _timestamp_verifier(timestamp_config, args.trust_store.parent)
        bundle_bytes = args.bundle.read_bytes()
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}, sort_keys=True))
        return 2

    report = verify_customer_bundle(
        bundle_bytes,
        trusted_keys=trusted,
        revoked_key_ids=revoked,
        timestamp_verifier=timestamp_verifier,
    )
    print(json.dumps({
        "status": report.status,
        "reason": report.reason,
        "igor_signature": report.igor_signature,
        "ola_signature": report.ola_signature,
        "manifest_sha256": report.manifest_sha256,
        "report_sha256": report.report_sha256,
        "timestamp_status": report.timestamp_status,
        "lifecycle_status": report.lifecycle_status,
        "bundle_id": report.bundle_id,
        "bundle_version": report.bundle_version,
        "profile": report.profile,
        "expires_at": report.expires_at,
        "full_tenant_chain_recomputed": report.full_tenant_chain_recomputed,
    }, sort_keys=True))
    if report.lifecycle_status == "EXPIRED":
        return 4
    if report.status == "VERIFIED":
        return 0
    if report.status == "PARTIAL":
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
