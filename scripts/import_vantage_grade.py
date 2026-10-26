"""Import a pinned Ed25519-signed Vantage v0.3 grading receipt into OLA Evidence v2.

This is an operator-triggered, one-way bridge, not live sync or execution authority.
Only hashes and provenance labels are persisted; an OLA tenant API key cannot
impersonate an internal trusted producer or approve Human Gate.
"""
import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.hashchain import (
    EVIDENCE_META_KEY, canonical_json, compute_record_hash_v2,
)

MAX_REPORT_BYTES = 256 * 1024
MAX_PUBLIC_KEY_BYTES = 8192
MAX_API_RESPONSE = 128 * 1024
RECORD_TYPE = "external.vantage.grade"
META = {"version": 2, "record_type": RECORD_TYPE, "producer": "tenant_api"}
SHA256 = re.compile(r"[0-9a-f]{64}\\Z")
HEX_HASH = re.compile(r"[0-9a-f]{64}\\Z")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def validate_ola_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("OLA URL required")
    p = urlsplit(url)
    if (not p.hostname or p.username is not None or p.password is not None
            or p.query or p.fragment or p.path not in ("", "/")
            or not p.port is None and not 1 <= p.port <= 65535):
        raise ValueError("OLA URL must be a clean service origin")
    if p.scheme != "https" and not (
        p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("HTTPS required outside local loopback")
    return url.rstrip("/")


def prepare_payload(report_path: Path, pubkey_path: Path, pin: str) -> dict:
    """Validate the report against a trusted public key digest before network I/O."""
    if not isinstance(pin, str) or SHA256.fullmatch(pin.lower()) is None:
        raise ValueError("trusted public-key SHA-256 pin is required")
    pin = pin.lower()
    pubkey_path = Path(pubkey_path)
    with pubkey_path.open("rb") as handle:
        key_data = handle.read(MAX_PUBLIC_KEY_BYTES + 1)
    if (not key_data or len(key_data) > MAX_PUBLIC_KEY_BYTES
            or b"-----BEGIN PUBLIC KEY-----" not in key_data):
        raise ValueError("grader public key is not a bounded PEM public key")
    key_hash = hashlib.sha256(key_data).hexdigest()
    if not hmac.compare_digest(pin, key_hash):
        raise ValueError("grader public-key pin does not match")
    report_path = Path(report_path)
    if report_path.suffix.lower() != ".json":
        raise ValueError("Vantage result must be a JSON report")
    with report_path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Vantage report is empty or too large")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed Vantage JSON report") from exc
    if (not isinstance(doc, dict) or doc.get("alg") != "ed25519"
            or doc.get("signed") != "canonical JSON of result"
            or not isinstance(doc.get("result"), dict)):
        raise ValueError("unsupported signed Vantage grade format")
    result = doc["result"]
    if (result.get("kind") not in (None, "grade")
            or not isinstance(result.get("attempt_id"), str)
            or not result["attempt_id"] or len(result["attempt_id"]) > 128
            or not isinstance(result.get("scenario"), str)
            or not result["scenario"] or len(result["scenario"]) > 128
            or type(result.get("attested")) is not bool
            or not isinstance(result.get("trust"), dict)
            or "score" not in result or "tier" not in result):
        raise ValueError("not a supported signed grader attempt")
    sig_b64 = doc.get("signature")
    if not isinstance(sig_b64, str) or len(sig_b64) > 512:
        raise ValueError("missing or oversized Vantage signature")
    try:
        sig = base64.b64decode(sig_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid Vantage signature encoding") from exc
    if len(sig) != 64:
        raise ValueError("invalid Vantage Ed25519 signature size")
    # Must match grader/server.py canonical() EXACTLY, including ensure_ascii=True.
    message = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        with tempfile.TemporaryDirectory() as workdir:
            msg = Path(workdir) / "message.bin"
            signature = Path(workdir) / "signature.bin"
            msg.write_bytes(message)
            signature.write_bytes(sig)
            completed = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey",
                 str(pubkey_path.resolve()), "-rawin", "-in", str(msg),
                 "-sigfile", str(signature)],
                capture_output=True, timeout=10, check=False,
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError("Ed25519 verifier unavailable") from exc
    if completed.returncode != 0:
        raise ValueError("Vantage signature invalid for pinned grader public key")
    return {
        "schema": "ola.external.vantage.grade.v1",
        "source": "vantage-v0.3-grader",
        "source_signature": "PINNED_ED25519_CHECK_PASSED",
        "producer_trust": "tenant_api_only",
        "claimed_attested": result["attested"],
        "signed_result_sha256": hashlib.sha256(message).hexdigest(),
        "original_report_sha256": hashlib.sha256(raw).hexdigest(),
        "signature_sha256": hashlib.sha256(sig).hexdigest(),
        "public_key_sha256": key_hash,
        "scenario_sha256": hashlib.sha256(result["scenario"].encode()).hexdigest(),
    }


def _request(url: str, key: str, method: str, payload: dict | None = None) -> dict:
    if method not in {"POST", "GET"}:
        raise ValueError("unsupported OLA API method")
    headers = {"X-API-Key": key, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = canonical_json(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(MAX_API_RESPONSE + 1)
            if not raw or len(raw) > MAX_API_RESPONSE:
                raise RuntimeError("OLA API response missing or oversized")
            doc = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError("OLA evidence API rejected request (HTTP %s)" % exc.code) from None
    except URLError:
        raise RuntimeError("OLA evidence API unavailable") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("OLA evidence API returned invalid JSON") from exc
    if not isinstance(doc, dict):
        raise RuntimeError("OLA evidence API returned non-object")
    return doc


def import_grade(report_path: Path, pubkey_path: Path, pin: str,
                 ola_url: str, expected_tenant: str, key: str | None,
                 *, dry_run: bool = False) -> dict:
    payload = prepare_payload(report_path, pubkey_path, pin)
    if dry_run:
        return {
            "status": "VALIDATED_NOT_RECORDED", "record_type": RECORD_TYPE,
            "source_signature": "PASS", "production_authorized": False,
            "payload": payload,
        }
    if not isinstance(key, str) or not key.strip():
        raise ValueError("OLA tenant API key is required")
    if not isinstance(expected_tenant, str) or not expected_tenant:
        raise ValueError("explicit expected OLA tenant is required")
    origin = validate_ola_url(ola_url)
    submitted = _request(origin + "/evidence", key, "POST", {
        "record_type": RECORD_TYPE, "payload": payload,
    })
    evidence_id = submitted.get("id")
    if not isinstance(evidence_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", evidence_id):
        raise RuntimeError("OLA evidence write produced invalid ID")
    fetched = _request(origin + "/evidence/" + evidence_id, key, "GET")
    actual_payload = fetched.get("payload")
    expected_payload = dict(payload)
    expected_payload[EVIDENCE_META_KEY] = META
    if (fetched.get("id") != evidence_id
            or fetched.get("tenant_id") != expected_tenant
            or submitted.get("tenant_id") != expected_tenant
            or fetched.get("record_type") != RECORD_TYPE
            or actual_payload != expected_payload):
        raise RuntimeError("OLA evidence tenant/type/payload mismatch")
    seq = fetched.get("seq")
    previous = fetched.get("prev_hash")
    recorded_hash = fetched.get("record_hash")
    if (type(seq) is not int or seq < 0
            or not isinstance(previous, str) or not HEX_HASH.fullmatch(previous)
            or not isinstance(recorded_hash, str) or not HEX_HASH.fullmatch(recorded_hash)):
        raise RuntimeError("OLA evidence sequence/hash fields invalid")
    expected_hash = compute_record_hash_v2(
        expected_tenant, seq, previous, RECORD_TYPE,
        "tenant_api", canonical_json(expected_payload),
    )
    if (not hmac.compare_digest(expected_hash, recorded_hash)
            or submitted.get("record_hash") != recorded_hash
            or submitted.get("seq") != seq):
        raise RuntimeError("OLA evidence record hash mismatch")
    return {
        "status": "RECORDED", "record_type": RECORD_TYPE, "evidence_id": evidence_id,
        "source_signature": "PASS", "record_integrity": "PASS",
        "producer_trust": "tenant_api_only", "production_authorized": False,
        "record_hash": recorded_hash, "report_sha256": payload["original_report_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--pubkey", type=Path, required=True)
    parser.add_argument("--ola-url", default=os.getenv("OLA_BASE_URL", ""))
    parser.add_argument("--tenant-id", default=os.getenv("OLA_TENANT_ID", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        outcome = import_grade(
            args.report, args.pubkey, os.getenv("VANTAGE_GRADER_PUBKEY_SHA256", ""),
            args.ola_url, args.tenant_id, os.getenv("OLA_API_KEY"),
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        # Avoid echoing tokens, secrets or potentially sensitive document content.
        print("BLOCKED: %s" % type(exc).__name__, file=sys.stderr)
        return 1
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
