#!/usr/bin/env python3
"""Offline verification of an OLA customer evidence ZIP."""
import argparse
import base64
import json
import sys
from pathlib import Path

from app.customer_bundle.verifier import verify_customer_bundle


def _read_trust_store(path: Path) -> tuple[dict[str, bytes], set[str]]:
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
    return trusted, set(revoked)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a dual-signed OLA customer evidence bundle offline.")
    parser.add_argument("bundle", type=Path, help="Customer evidence ZIP")
    parser.add_argument("--trust-store", required=True, type=Path, help="Out-of-band trusted Ed25519 public key JSON")
    args = parser.parse_args()

    try:
        trusted, revoked = _read_trust_store(args.trust_store)
        bundle_bytes = args.bundle.read_bytes()
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}, sort_keys=True))
        return 2

    report = verify_customer_bundle(
        bundle_bytes,
        trusted_keys=trusted,
        revoked_key_ids=revoked,
    )
    print(json.dumps({
        "status": report.status,
        "reason": report.reason,
        "igor_signature": report.igor_signature,
        "ola_signature": report.ola_signature,
        "manifest_sha256": report.manifest_sha256,
        "report_sha256": report.report_sha256,
        "timestamp_status": report.timestamp_status,
        "full_tenant_chain_recomputed": report.full_tenant_chain_recomputed,
    }, sort_keys=True))
    if report.status == "VERIFIED":
        return 0
    if report.status == "PARTIAL":
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
