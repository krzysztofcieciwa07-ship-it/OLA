"""Read-only, provenance-aware public CVE enrichment (CISA KEV + FIRST EPSS).

No Recorded Future data, credentials, asset inventory, LLM calls, or autonomous actions.
The returned status describes observations, not an independently verified decision.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Callable

import httpx

CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EPSS_API_URL = "https://api.first.org/data/v1/epss"
_CVE_PATTERN = re.compile(r"CVE-(?:19|20)\d{2}-[0-9]{4,}", re.ASCII)
_MAX_BYTES = 8 * 1024 * 1024


def _fetch_public_json(url: str) -> bytes:
    # Callers cannot supply a URL: lookup_cve constructs one of two fixed upstreams.
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
            if response.status_code != 200:
                raise ValueError("public source returned a non-200 status")
            parts = []
            total = 0
            for part in response.iter_bytes():
                total += len(part)
                if total > _MAX_BYTES:
                    raise ValueError("feed exceeds size cap")
                parts.append(part)
            return b"".join(parts)


def _decode_json(payload: bytes) -> dict:
    if not isinstance(payload, bytes) or len(payload) > _MAX_BYTES:
        raise ValueError("invalid feed body")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("invalid feed schema")
    return data


def _kev_signal(document: dict, cve: str) -> tuple[bool, dict | None]:
    rows = document.get("vulnerabilities")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid KEV feed")
    for entry in rows:
        if entry.get("cveID") == cve:
            return True, {"date_added": entry.get("dateAdded"), "vendor": entry.get("vendorProject"), "product": entry.get("product")}
    return False, None


def _epss_signal(document: dict, cve: str) -> tuple[float, float]:
    rows = document.get("data")
    if document.get("status") != "OK" or not isinstance(rows, list):
        raise ValueError("invalid EPSS response")
    matches = [row for row in rows if isinstance(row, dict) and row.get("cve") == cve]
    if len(matches) != 1:
        raise ValueError("EPSS result missing or ambiguous")
    score = float(matches[0]["epss"])
    percentile = float(matches[0]["percentile"])
    if not (math.isfinite(score) and math.isfinite(percentile) and 0 <= score <= 1 and 0 <= percentile <= 1):
        raise ValueError("invalid EPSS value")
    return score, percentile


def lookup_cve(cve_id: str, *, fetch_bytes: Callable[[str], bytes] | None = None,
               retrieved_at: str | None = None) -> dict:
    """Enrich one CVE with independent public signals; fail closed on missing feeds.

    A source digest proves equality to the bytes fetched in this run, *not* origin
    authenticity. It is not a signature or an approval to act on infrastructure.
    """
    if not isinstance(cve_id, str):
        raise ValueError("invalid CVE ID")
    cve = cve_id.upper()
    if not _CVE_PATTERN.fullmatch(cve):
        raise ValueError("invalid CVE ID")
    fetch = fetch_bytes or _fetch_public_json
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    sources = []
    signals = {"in_cisa_kev": None, "kev_detail": None, "epss_probability": None, "epss_percentile": None}

    for name, url in (("CISA_KEV", CISA_KEV_URL), ("FIRST_EPSS", EPSS_API_URL + "?cve=" + cve)):
        try:
            raw = fetch(url)
            document = _decode_json(raw)
            if name == "CISA_KEV":
                signals["in_cisa_kev"], signals["kev_detail"] = _kev_signal(document, cve)
            else:
                signals["epss_probability"], signals["epss_percentile"] = _epss_signal(document, cve)
            sources.append({"name": name, "url": url, "sha256": hashlib.sha256(raw).hexdigest(), "retrieved_at": timestamp})
        except (ValueError, TypeError, LookupError, OSError, KeyError, httpx.HTTPError):
            # Never expose upstream error messages; they can contain sensitive URLs.
            continue

    status = "OBSERVED" if len(sources) == 2 else "PARTIAL" if sources else "UNKNOWN"
    triage = ("REVIEW_REQUIRED" if status != "OBSERVED"
              else "PRIORITIZE_REVIEW" if signals["in_cisa_kev"] is True
              else "ASSESS_EXPOSURE")
    return {"schema": "ola.threat-intelligence.v0", "cve": cve, "status": status,
            "signals": signals, "triage": triage, "sources": sources,
            "decision_verified": False, "write_actions_permitted": False}


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m app.threat_intelligence CVE-YYYY-NNNN", file=sys.stderr)
        sys.exit(2)
    try:
        result = lookup_cve(sys.argv[1])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.exit(0 if result["status"] == "OBSERVED" else 3)
