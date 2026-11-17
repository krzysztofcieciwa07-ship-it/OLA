"""Deterministic contract tests for public-source CVE enrichment."""
import hashlib
import json

import pytest

from app.threat_intelligence import CISA_KEV_URL, EPSS_API_URL, lookup_cve


CVE = "CVE-2024-12345"


def feeds(*, known=True, score="0.812345"):
    kev = {"catalogVersion": "2026.10.11", "vulnerabilities": [{"cveID": CVE, "dateAdded": "2026-10-10", "vendorProject": "Example"}] if known else []}
    epss = {"status": "OK", "data": [{"cve": CVE, "epss": score, "percentile": "0.990"}]}
    return json.dumps(kev).encode(), json.dumps(epss).encode()


def test_kev_and_epss_expose_traced_signals_without_fake_verification():
    kev, epss = feeds()
    calls = []
    def fetch(url):
        calls.append(url)
        return kev if url == CISA_KEV_URL else epss

    result = lookup_cve("cve-2024-12345", fetch_bytes=fetch, retrieved_at="2026-10-11T00:00:00Z")
    assert result["cve"] == CVE
    assert result["status"] == "OBSERVED"
    assert result["signals"]["in_cisa_kev"] is True
    assert result["signals"]["epss_probability"] == 0.812345
    assert result["signals"]["epss_percentile"] == 0.99
    assert result["triage"] == "PRIORITIZE_REVIEW"
    assert [x["url"] for x in result["sources"]] == [CISA_KEV_URL, EPSS_API_URL + "?cve=" + CVE]
    assert result["sources"][0]["sha256"] == hashlib.sha256(kev).hexdigest()
    assert result["sources"][0]["retrieved_at"] == "2026-10-11T00:00:00Z"
    assert len(calls) == 2
    assert result["decision_verified"] is False


def test_absent_from_kev_does_not_mean_safe():
    kev, epss = feeds(known=False)
    result = lookup_cve(CVE, fetch_bytes=lambda u: kev if u == CISA_KEV_URL else epss)
    assert result["status"] == "OBSERVED"
    assert result["signals"]["in_cisa_kev"] is False
    assert result["triage"] == "ASSESS_EXPOSURE"
    assert result["decision_verified"] is False


def test_source_failure_returns_partial_without_promoting_signal():
    kev, _ = feeds()
    def fetch(url):
        if url == CISA_KEV_URL:
            return kev
        raise OSError("credential=secret-not-for-output")
    result = lookup_cve(CVE, fetch_bytes=fetch)
    assert result["status"] == "PARTIAL"
    assert result["signals"]["epss_probability"] is None
    assert result["triage"] == "REVIEW_REQUIRED"
    assert len(result["sources"]) == 1
    assert "secret" not in json.dumps(result)


def test_all_failed_is_unknown_and_has_no_sources():
    def fail(url):
        raise OSError("offline")
    result = lookup_cve(CVE, fetch_bytes=fail)
    assert result["status"] == "UNKNOWN"
    assert result["sources"] == []
    assert result["triage"] == "REVIEW_REQUIRED"


def test_malformed_json_and_mismatched_epss_never_accepted():
    kev, _ = feeds()
    bad = json.dumps({"status": "OK", "data": [{"cve": "CVE-2025-1234", "epss": "0.99", "percentile": "0.99"}]}).encode()
    r = lookup_cve(CVE, fetch_bytes=lambda u: kev if u == CISA_KEV_URL else bad)
    assert r["status"] == "PARTIAL"
    assert r["signals"]["epss_probability"] is None
    r2 = lookup_cve(CVE, fetch_bytes=lambda _: b"not-json")
    assert r2["status"] == "UNKNOWN"


@pytest.mark.parametrize("bad", ["http://example.com", "CVE-2024-1", "CVE-2024-1234?x=y", "CVE-2024-1234/../../metadata", "", "CVE-2024-01234\nX"])
def test_invalid_cve_is_rejected_before_any_network_io(bad):
    called = []
    with pytest.raises(ValueError):
        lookup_cve(bad, fetch_bytes=lambda url: called.append(url))
    assert not called


def test_out_of_range_epss_is_not_accepted():
    kev, epss = feeds(score="1.01")
    r = lookup_cve(CVE, fetch_bytes=lambda u: kev if u == CISA_KEV_URL else epss)
    assert r["status"] == "PARTIAL"
    assert r["signals"]["epss_probability"] is None


def test_http_client_timeout_is_unknown_and_never_leaks_remote_error():
    import httpx

    def fetch(url):
        raise httpx.ReadTimeout("https://example.test/private-token")

    r = lookup_cve(CVE, fetch_bytes=fetch)
    assert r["status"] == "UNKNOWN"
    assert r["write_actions_permitted"] is False
    assert "private-token" not in json.dumps(r)
