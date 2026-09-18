import json

from app.contradiction import detect_contradictions
from app.replay import build_replay


def test_detects_conflicting_terminal_results():
    records = [
        {"seq": 0, "payload_json": json.dumps({"run_id": "r1", "status": "VERIFIED", "result": "391"})},
        {"seq": 1, "payload_json": json.dumps({"run_id": "r1", "status": "BLOCK", "result": "392"})},
    ]
    findings = detect_contradictions(records)
    assert findings[0]["type"] == "terminal_result_conflict"


def test_replay_is_ordered_and_deterministic():
    records = [
        {"seq": 1, "record_type": "agent.react", "payload_json": json.dumps({"run_id": "r1", "input_digest": "b", "tool": "react"})},
        {"seq": 0, "record_type": "agent.codeact", "payload_json": json.dumps({"run_id": "r1", "input_digest": "a", "tool": "safe_expression"})},
    ]
    first = build_replay(records)
    second = build_replay(records)
    assert first == second
    assert [item["seq"] for item in first] == [0, 1]
