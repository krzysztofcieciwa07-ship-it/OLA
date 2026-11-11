import json

from .hashchain import verify_chain, trusted_record


def build_replay(records):
    replay = []
    for record in sorted(records, key=lambda item: item["seq"]):
        try:
            payload = json.loads(record["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            replay.append({
                "id": record.get("id"),
                "tenant_id": record.get("tenant_id"),
                "seq": record["seq"],
                "record_type": record.get("record_type"),
                "run_id": payload.get("run_id"),
                "input_digest": payload.get("input_digest"),
                "tool": payload.get("tool"),
                "status": payload.get("status"),
            })
        else:
            replay.append({
                "id": record.get("id"),
                "tenant_id": record.get("tenant_id"),
                "seq": record.get("seq"),
                "record_type": record.get("record_type"),
                "run_id": None,
                "input_digest": None,
                "tool": None,
                "status": None,
            })
    return replay


def verify_replay(records, expected_run_id, expected_tenant_id,
                  expected_record_count=None, expected_tip_hash=None):
    if not records:
        return {"status": "UNKNOWN", "reason": "replay is empty", "event_count": 0}

    if expected_record_count is not None and len(records) != expected_record_count:
        return {"status": "BLOCK", "reason": "record count mismatch", "event_count": len(records),
                "expected_record_count": expected_record_count}

    for record in records:
        if not isinstance(record, dict):
            return {"status": "BLOCK", "reason": "record must be a dict", "event_count": len(records)}
        required = {"tenant_id", "seq", "prev_hash", "record_hash", "record_type", "payload_json"}
        if not required.issubset(record):
            return {"status": "BLOCK", "reason": "evidence record is incomplete", "event_count": len(records)}
        if record.get("tenant_id") != expected_tenant_id:
            return {"status": "BLOCK", "reason": "tenant provenance mismatch", "event_count": len(records)}
        if not isinstance(record.get("record_type"), str) or not record["record_type"]:
            return {"status": "BLOCK", "reason": "record type is missing", "event_count": len(records)}
        if not isinstance(record.get("payload_json"), str):
            return {"status": "BLOCK", "reason": "missing payload_json", "event_count": len(records)}
        try:
            payload = json.loads(record["payload_json"])
        except json.JSONDecodeError:
            return {"status": "BLOCK", "reason": "invalid payload_json", "event_count": len(records)}
        if not isinstance(payload, dict):
            return {"status": "BLOCK", "reason": "payload must be a dict", "event_count": len(records)}

    chain_ok, reason = verify_chain(records)
    if not chain_ok:
        return {"status": "BLOCK", "reason": reason, "event_count": len(records)}

    if expected_tip_hash is not None and records[-1].get("record_hash") != expected_tip_hash:
        return {"status": "BLOCK", "reason": "tip hash mismatch", "event_count": len(records),
                "tip_hash": records[-1].get("record_hash")}

    run_record_count = 0
    execution_boundaries = set()
    worker_pids = set()
    parent_pids = set()
    for record in records:
        payload = json.loads(record["payload_json"])
        if payload.get("run_id") == expected_run_id and record.get("record_type", "").startswith("agent."):
            if not trusted_record(record):
                return {"status": "BLOCK", "reason": "legacy or untrusted agent evidence", "event_count": len(records)}
            expected_type = f"agent.{payload.get('agent', '')}"
            if payload.get("agent") is None or record["record_type"] != expected_type:
                return {"status": "BLOCK", "reason": "run record type mismatch", "event_count": len(records)}
            if payload.get("status") != "RECORDED":
                return {"status": "BLOCK", "reason": "producer record must be RECORDED, not self-verified", "event_count": len(records)}
            boundary = payload.get("execution_boundary")
            if boundary == "in_process":
                execution_boundaries.add(boundary)
            elif boundary == "subprocess":
                worker_pid = payload.get("worker_pid")
                parent_pid = payload.get("worker_parent_pid")
                if (type(worker_pid) is not int or worker_pid <= 0
                        or type(parent_pid) is not int or parent_pid <= 0
                        or worker_pid == parent_pid
                        or not isinstance(payload.get("worker_request_id"), str)
                        or not payload["worker_request_id"]):
                    return {"status": "BLOCK", "reason": "invalid worker process evidence", "event_count": len(records)}
                worker_pids.add(worker_pid)
                parent_pids.add(parent_pid)
                execution_boundaries.add(boundary)
            else:
                return {"status": "BLOCK", "reason": "unexpected agent execution boundary", "event_count": len(records)}
            if (payload.get("model_output_role") != "advisory_only"
                    or payload.get("action_result_source") != "registered_capability"):
                return {"status": "BLOCK", "reason": "ambiguous model/action provenance", "event_count": len(records)}
            run_record_count += 1

    if run_record_count == 0:
        return {"status": "BLOCK", "reason": "run provenance mismatch", "event_count": len(records)}
    if "subprocess" in execution_boundaries:
        if len(worker_pids) != run_record_count or len(parent_pids) != 1:
            return {"status": "BLOCK", "reason": "worker process identities are not unique children of one orchestrator", "event_count": len(records)}

    not_established = []
    if "in_process" in execution_boundaries:
        not_established.append("isolated_or_independent_agent_processes")
    if "subprocess" in execution_boundaries:
        not_established.extend([
            "hardened_os_sandbox_and_filesystem_isolation",
            "worker_network_egress_isolation",
        ])
    not_established.extend([
        "semantic_correctness_of_registered_capabilities",
        "model_generated_action_results",
    ])

    return {
        "status": "VERIFIED",
        "reason": "raw evidence records, producer status, process identities, provenance and hash chain verified",
        "verification_scope": [
            "raw_record_structure",
            "producer_status_is_recorded",
            "execution_boundary_and_worker_identity_evidence",
            "model_and_action_result_sources_are_distinguished",
            "tenant_hash_chain_integrity",
        ],
        "execution_boundaries": sorted(execution_boundaries),
        "worker_process_count": len(worker_pids),
        "not_established": not_established,
        "event_count": len(records),
        "run_event_count": run_record_count,
        "run_id": expected_run_id,
        "tenant_id": expected_tenant_id,
        "first_seq": 0,
        "last_seq": records[-1]["seq"],
        "tip_hash": records[-1]["record_hash"],
    }
