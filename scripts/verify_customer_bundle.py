#!/usr/bin/env python3
"""Verify an OLA customer evidence ZIP; OCI SLSA uses a local bundle/root and pinned registry subject."""
import argparse
import base64
import json
import re
import sys
import subprocess
from datetime import datetime, timezone
import tempfile
from pathlib import Path


def _read_trust_store(path: Path) -> tuple[dict[str, bytes], set[str], dict | None, dict | None]:
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
    provenance = data.get("provenance")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance trust settings must be an object")
    return trusted, set(revoked), timestamp, provenance


def _timestamp_verifier(config: dict | None, trust_store_dir: Path):
    if not isinstance(config, dict):
        return None
    ca_value = config.get("ca_file")
    untrusted_value = config.get("untrusted_file")
    max_gen_time_delay = config.get("max_gen_time_delay_seconds", 300)
    if type(max_gen_time_delay) is not int or not 1 <= max_gen_time_delay <= 3600:
        return None
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
                if result.returncode != 0:
                    return False
                details = subprocess.run(
                    ["openssl", "ts", "-reply", "-in", str(token_path), "-text"],
                    capture_output=True, text=True, check=False, timeout=20,
                )
                if details.returncode != 0:
                    return False
                match = re.search(r"^\s*Time stamp:\s*(.+?)\s*$", details.stdout, re.MULTILINE)
                if match is None:
                    return False
                timestamp_text = match.group(1)
                if not timestamp_text.endswith(" GMT"):
                    return False
                parsed = datetime.strptime(
                    timestamp_text[:-4].strip(), "%b %d %H:%M:%S %Y",
                ).replace(tzinfo=timezone.utc)
                gen_time = int(parsed.timestamp())
                return signed_at <= gen_time <= signed_at + max_gen_time_delay
        except (OSError, subprocess.SubprocessError):
            return False

    return verify


def _provenance_verifier(config: dict | None):
    if not isinstance(config, dict):
        return None
    required_strings = (
        "repository", "repository_id", "workflow_identity", "trusted_root_sha256",
    )
    if any(not isinstance(config.get(key), str) or not config[key] for key in required_strings):
        return None
    run_id = config.get("run_id")
    run_attempt = config.get("run_attempt")
    if type(run_id) is not int or run_id < 1 or type(run_attempt) is not int or run_attempt < 1:
        return None
    source_ref = config.get("source_ref", "refs/heads/main")
    image_name = config.get("image_name")
    gh_binary = config.get("gh_binary", "gh")
    if not isinstance(source_ref, str) or not source_ref:
        return None
    if image_name is not None and (not isinstance(image_name, str) or not image_name):
        return None
    if not isinstance(gh_binary, str) or not gh_binary:
        return None

    from app.customer_bundle.github_provenance import github_oci_provenance_verifier

    return github_oci_provenance_verifier(
        expected_repository=config["repository"],
        expected_repository_id=config["repository_id"],
        expected_workflow_identity=config["workflow_identity"],
        expected_source_ref=source_ref,
        expected_image_name=image_name,
        expected_trusted_root_sha256=config["trusted_root_sha256"],
        expected_run_id=run_id,
        expected_run_attempt=run_attempt,
        gh_binary=gh_binary,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a dual-signed OLA customer evidence bundle and its OCI SLSA provenance.")
    parser.add_argument("bundle", type=Path, help="Customer evidence ZIP")
    parser.add_argument("--trust-store", required=True, type=Path, help="Out-of-band trusted Ed25519 public key JSON")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from app.customer_bundle.verifier import verify_customer_bundle

    try:
        trusted, revoked, timestamp_config, provenance_config = _read_trust_store(args.trust_store)
        timestamp_verifier = _timestamp_verifier(timestamp_config, args.trust_store.parent)
        provenance_verifier = _provenance_verifier(provenance_config)
        bundle_bytes = args.bundle.read_bytes()
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}, sort_keys=True))
        return 2

    report = verify_customer_bundle(
        bundle_bytes,
        trusted_keys=trusted,
        revoked_key_ids=revoked,
        timestamp_verifier=timestamp_verifier,
        provenance_verifier=provenance_verifier,
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
