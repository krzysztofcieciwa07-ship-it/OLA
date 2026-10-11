from app.replay import verify_replay


def _invalid_record(**overrides):
    record = {
        "tenant_id": "tenant-1", "seq": 0, "prev_hash": "0" * 64,
        "record_hash": "f" * 64, "record_type": "agent.codeact",
        "payload_json": '{"run_id":"r1","agent":"codeact","status":"VERIFIED"}',
    }
    record.update(overrides)
    return record


def test_malformed_sequence_blocks_without_exception():
    for value in (None, True, "0", -1, 0.0):
        result = verify_replay([_invalid_record(seq=value)], "r1", "tenant-1")
        assert result["status"] == "BLOCK"
        assert result["reason"] == "invalid sequence"


def test_malformed_hash_field_blocks_without_exception():
    for field in ("prev_hash", "record_hash"):
        for value in (None, 0, [], {}):
            result = verify_replay([_invalid_record(**{field: value})], "r1", "tenant-1")
            assert result["status"] == "BLOCK"
            assert result["reason"] == "invalid hash field"
