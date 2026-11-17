"""Import a user-exported Scrudix report into the existing OLA evidence API.

No Scrudix API endpoint or Scrudix credential is used: its report API is not
documented. This records a content hash, not a verified Scrudix attestation.
Run from the repository root: python -m scripts.import_scrudix_report --help
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.hashchain import canonical_json, compute_record_hash


MAX_REPORT_BYTES = 2 * 1024 * 1024
RECORD_TYPE = "external.scrudix.report"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None  # Never forward the OLA API key to a redirected host.


def build_report_payload(path: Path) -> dict:
    if path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("expected a Scrudix Markdown/text export")
    with path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ValueError("report is empty or exceeds 2 MiB")
    try:
        report = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("report must be UTF-8") from exc
    if "Scrudix Usage Reports Export" not in report[:1024]:
        raise ValueError("not a recognized Scrudix usage report export")

    generated = re.search(r"^Generated:\s*(\S+)", report, re.MULTILINE)
    payload = {
        "schema": "ola.external-report.v1",
        "source": "scrudix.user_export",
        "source_authenticity": "UNVERIFIED",
        "file_name": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    if generated:
        payload["claimed_generated_at"] = generated.group(1)
    return payload


def validate_ola_url(url: str) -> str:
    parts = urlsplit(url)
    if (not parts.hostname or parts.username or parts.password or parts.query
            or parts.fragment or parts.path not in {"", "/"}):
        raise ValueError("OLA URL must be a service origin without credentials or path")
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("HTTPS is required except for local loopback")
    return url.rstrip("/")


def _request(url: str, key: str, method: str, payload: dict | None = None) -> dict:
    headers = {"X-API-Key": key, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = canonical_json(payload).encode("utf-8")
    request = Request(url, headers=headers, data=data, method=method)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"OLA API returned HTTP {exc.code}") from None
    except URLError:
        raise RuntimeError("OLA API is unreachable") from None


def import_report(path: Path, ola_url: str, key: str | None, *, dry_run: bool = False) -> dict:
    payload = build_report_payload(path)
    if dry_run:
        return {"status": "DRY_RUN", "record_type": RECORD_TYPE, "payload": payload}
    if not key:
        raise ValueError("OLA_API_KEY must be configured for import")
    origin = validate_ola_url(ola_url)
    written = _request(origin + "/evidence", key, "POST", {
        "record_type": RECORD_TYPE, "payload": payload,
    })
    if not written.get("id"):
        raise RuntimeError("OLA did not return an evidence record ID")
    record = _request(origin + "/evidence/" + written["id"], key, "GET")
    if record.get("payload") != payload or record.get("record_type") != RECORD_TYPE:
        raise RuntimeError("OLA evidence read-back mismatch")
    expected = compute_record_hash(
        record["tenant_id"], record["seq"], record["prev_hash"], canonical_json(payload)
    )
    if record.get("record_hash") != expected or written.get("record_hash") != expected:
        raise RuntimeError("OLA evidence record hash mismatch")
    return {
        "status": "RECORDED", "source_authenticity": "UNVERIFIED",
        "record_integrity": "PASS", "evidence_id": written["id"],
        "record_hash": expected, "report_sha256": payload["sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Scrudix .md or .txt usage export")
    parser.add_argument("--ola-url", default=os.getenv("OLA_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--dry-run", action="store_true", help="No network request, no API key needed")
    args = parser.parse_args()
    try:
        result = import_report(args.report, args.ola_url, os.getenv("OLA_API_KEY"),
                               dry_run=args.dry_run)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Scrudix import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
