from types import SimpleNamespace

from app.gate_impact import build_gate_funnel, classify_impact


def record(seq, record_type, payload):
    import json
    return SimpleNamespace(seq=seq, record_type=record_type, payload_json=json.dumps(payload))


def test_gate_funnel_uses_runtime_statuses_and_keeps_missing_stages_unknown():
    rows = [
        record(0, "agent.codeact", {"status": "VERIFIED"}),
        record(1, "runtime", {"nina_status": "ALLOW", "igor_status": "VERIFIED"}),
        record(2, "runtime", {"human_gate_status": "BLOCK"}),
    ]
    result = build_gate_funnel(rows)
    assert result["stages"]["nina"]["status"] == "ALLOW"
    assert result["stages"]["igor"]["status"] == "VERIFIED"
    assert result["stages"]["human_gate"]["status"] == "BLOCK"
    assert result["counts"]["VERIFIED"] == 2


def test_impact_prefers_explicit_payload_risk():
    rows = [record(0, "audit", {"risk": "high"})]
    result = classify_impact(rows)
    assert result["classification"] == "HIGH"
    assert result["confidence"] == "EXPLICIT"


def test_impact_does_not_fake_a_risk_field():
    rows = [record(0, "audit", {"status": "VERIFIED"})]
    result = classify_impact(rows)
    assert result["classification"] == "NO_EXPLICIT_RISK"
    assert result["confidence"] == "UNKNOWN"
