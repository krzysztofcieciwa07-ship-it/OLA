import json

from app.igor import IgorVerifier


def test_igor_clean_run_verifies():
    verifier = IgorVerifier()
    result = verifier.verify_records(
        records=[
            {"seq": 0, "prev_hash": "0" * 64, "record_hash": "a" * 64, "payload_json": json.dumps({"run_id": "r1", "commit": "abc", "task": "Calculate 17 * 23", "result": "391"})}
        ],
        expected_commit="abc",
        expected_task="Calculate 17 * 23",
        expected_result="391",
    )
    assert result.status in {"VERIFIED", "BLOCK"}
    assert "chain" in result.checks


def test_igor_wrong_commit_blocks():
    verifier = IgorVerifier()
    result = verifier.verify_records(
        records=[
            {"seq": 0, "prev_hash": "0" * 64, "record_hash": "a" * 64, "payload_json": json.dumps({"run_id": "r1", "commit": "abc", "task": "Calculate 17 * 23", "result": "391"})}
        ],
        expected_commit="wrong",
        expected_task="Calculate 17 * 23",
        expected_result="391",
    )
    assert result.status == "BLOCK"
    assert result.reason == "commit provenance mismatch"


def test_igor_missing_evidence_is_not_verified():
    result = IgorVerifier().verify_records([], "abc", "task", "result")
    assert result.status == "UNKNOWN"
