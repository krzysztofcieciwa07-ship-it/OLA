import time
import pytest
from app.request_guard import RequestGuard
from app.data_refresh import FreshnessRegistry

def test_request_guard_rate_limits():
    g=RequestGuard(limit=2,window_seconds=60)
    assert g.allow("a",100) and g.allow("a",100) and not g.allow("a",100)

def test_request_guard_rejects_oversized_body():
    assert RequestGuard(max_body_bytes=10).body_allowed("10")
    assert not RequestGuard(max_body_bytes=10).body_allowed("11")
    assert not RequestGuard(max_body_bytes=10).body_allowed("invalid")

def test_freshness_registry_is_fail_closed_for_unknown_source():
    with pytest.raises(KeyError): FreshnessRegistry().policy("unknown")

def test_freshness_registry_detects_stale():
    r=FreshnessRegistry({"market":60}).evaluate("market",time.time()-61)
    assert r["status"]=="STALE"
