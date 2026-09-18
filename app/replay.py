import json


def build_replay(records):
    replay = []
    for record in sorted(records, key=lambda item: item["seq"]):
        payload = json.loads(record["payload_json"])
        replay.append({
            "seq": record["seq"],
            "record_type": record.get("record_type"),
            "run_id": payload.get("run_id"),
            "input_digest": payload.get("input_digest"),
            "tool": payload.get("tool"),
            "status": payload.get("status"),
        })
    return replay
