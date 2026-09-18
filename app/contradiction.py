import json


def detect_contradictions(records):
    payloads = [(record.get("seq"), json.loads(record["payload_json"])) for record in records]
    findings = []
    terminal = {}
    for seq, payload in payloads:
        run_id = payload.get("run_id")
        if run_id is None:
            continue
        key = run_id
        current = (payload.get("status"), str(payload.get("result")))
        if key in terminal and terminal[key][1] != current:
            findings.append({"type": "terminal_result_conflict", "run_id": key, "seq": seq, "previous": terminal[key][1], "current": current})
        terminal[key] = (seq, current)
    return findings
