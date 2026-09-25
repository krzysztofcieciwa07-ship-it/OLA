import json


KNOWN_STATUSES = {"ALLOW", "BLOCK", "UNKNOWN", "VERIFIED"}


def _payload(record):
    try:
        value = json.loads(record.payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _status_values(payload):
    values = []
    for key in ("status", "nina_status", "igor_status", "human_gate_status", "candidate_status"):
        value = payload.get(key)
        if isinstance(value, str) and value in KNOWN_STATUSES:
            values.append((key, value))
    return values


def build_gate_funnel(records):
    """Build only from states actually present in evidence payloads.

    The source runtime uses ALLOW/BLOCK/UNKNOWN/VERIFIED at its decision
    boundaries. Missing stages remain UNKNOWN rather than being inferred from
    frontend/demo labels.
    """
    counts = {status: 0 for status in sorted(KNOWN_STATUSES)}
    observed = []
    for record in records:
        payload = _payload(record)
        for key, status in _status_values(payload):
            counts[status] += 1
            observed.append({"seq": record.seq, "record_type": record.record_type, "field": key, "status": status})

    latest = {}
    for item in observed:
        latest[item["field"]] = item

    stages = {
        "nina": {"status": latest.get("nina_status", {}).get("status", "UNKNOWN")},
        "igor": {"status": latest.get("igor_status", {}).get("status", "UNKNOWN")},
        "human_gate": {"status": latest.get("human_gate_status", {}).get("status", "UNKNOWN")},
    }
    if not any(item["field"] == "nina_status" for item in observed):
        for item in observed:
            if item["record_type"].startswith("agent.") and item["status"] == "VERIFIED":
                stages["nina"] = {"status": "VERIFIED", "source": "agent evidence", "seq": item["seq"]}
                break

    return {
        "source": "evidence_records.payload_json",
        "rule": "only explicit runtime decision fields are classified; absent stages stay UNKNOWN",
        "counts": counts,
        "stages": stages,
        "observed": observed,
    }


def classify_impact(records):
    """Classify observed impact without inventing a risk field.

    Preferred source is payload_json.risk/impact. If neither exists, a
    deterministic evidence-based fallback is used: BLOCK/UNKNOWN states are
    operationally notable, but are reported as INFERRED rather than as a
    source-declared risk. No record -> UNKNOWN.
    """
    explicit = []
    for record in records:
        payload = _payload(record)
        risk = payload.get("risk", payload.get("impact"))
        if isinstance(risk, str) and risk.strip():
            explicit.append({"seq": record.seq, "record_type": record.record_type, "risk": risk.strip().upper(), "source": "payload_json"})

    if explicit:
        return {
            "classification": explicit[-1]["risk"],
            "confidence": "EXPLICIT",
            "source": "evidence_records.payload_json",
            "rule": "latest explicit payload_json.risk or payload_json.impact wins",
            "observations": explicit,
        }

    blocked = 0
    unknown = 0
    for record in records:
        payload = _payload(record)
        for _, status in _status_values(payload):
            blocked += status == "BLOCK"
            unknown += status == "UNKNOWN"

    if not records:
        classification = "UNKNOWN"
    elif blocked or unknown:
        classification = "OPERATIONAL_ATTENTION"
    else:
        classification = "NO_EXPLICIT_RISK"

    return {
        "classification": classification,
        "confidence": "INFERRED" if classification == "OPERATIONAL_ATTENTION" else "UNKNOWN",
        "source": "derived from observed decision states; no payload risk field exists",
        "rule": "BLOCK/UNKNOWN => OPERATIONAL_ATTENTION; otherwise NO_EXPLICIT_RISK; empty evidence => UNKNOWN",
        "observed_records": len(records),
    }
