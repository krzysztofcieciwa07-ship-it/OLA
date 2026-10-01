import time
from app.security_controls import redact, provenance_marker, check_freshness, compare_market_price

def test_redaction_masks_sensitive_fields_and_common_secrets():
    value={"api_key":"sk-secret-value","nested":{"password":"x","email":"jan@example.com","phone":"+32 471 12 34 56"},"normal":"hello"}
    out=redact(value)
    assert out["api_key"]=="[REDACTED]" and out["nested"]["password"]=="[REDACTED]"
    assert "jan@example.com" not in str(out) and "471 12 34 56" not in str(out)

def test_redaction_is_recursive_and_does_not_change_numbers():
    assert redact({"amount":123.45,"items":[{"secret":"x"}]})=={"amount":123.45,"items":[{"secret":"[REDACTED]"}]}

def test_provenance_marker_is_deterministic():
    a=provenance_marker("t",1,"0"*64,'{"x":1}')
    assert a==provenance_marker("t",1,"0"*64,'{"x":1}')
    assert len(a)==64 and a!=provenance_marker("t",2,"0"*64,'{"x":1}')

def test_freshness_stale_is_fail_closed():
    r=check_freshness(time.time()-120,60,"market-a")
    assert r.status=="STALE"

def test_market_conflict_requires_review():
    r=compare_market_price(100,[100,160],"EUR",10)
    assert r.status=="REVIEW" and r.spread_pct>10

def test_market_price_within_tolerance_passes():
    r=compare_market_price(105,[100,102,104],"EUR",10)
    assert r.status=="PASS"

def test_market_outlier_requires_review():
    r=compare_market_price(150,[100,101,99],"EUR",10)
    assert r.status=="REVIEW"
