import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path


GENESIS_HASH = "0" * 64
V2_KEY = "__ola_evidence_v2__"
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
CONTAINER_PATTERN = re.compile(r"^[a-f0-9]{64}$")
EXPECTED_EVENT_ORDER = [
    "execution.run.start",
    "agent.provider.response",
    "agent.worker.start",
    "agent.worker.end",
    "execution.run.end",
]


def fail(reason, **extra):
    return {"status": "BLOCK", "reason": reason, **extra}


def independent_record_hash(tenant_id, seq, record_type, payload_json, prev_hash):
    """Independent implementation; this verifier imports no OLA runtime code."""
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        return None
    metadata = payload.get(V2_KEY)
    if metadata is None:
        return hashlib.sha256(
            f"{tenant_id}|{seq}|{prev_hash}|{payload_json}".encode("utf-8")
        ).hexdigest()
    if (
        not isinstance(metadata, dict)
        or metadata != {
            "version": 2,
            "record_type": record_type,
            "producer": metadata.get("producer"),
        }
        or metadata.get("producer") not in ("ola_runtime", "tenant_api")
        or (
            record_type.startswith((
                "agent.", "workflow.", "task.", "human.", "provenance.",
                "decision.", "execution.", "verification.",
            ))
            and metadata.get("producer") != "ola_runtime"
        )
    ):
        return None
    material = json.dumps(
        {
            "domain": "OLA-EVIDENCE-CHAIN-V2",
            "tenant_id": tenant_id,
            "seq": seq,
            "prev_hash": prev_hash,
            "record_type": record_type,
            "producer": metadata["producer"],
            "payload_json": payload_json,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def verify_hash_chain(rows):
    expected_prev = GENESIS_HASH
    for expected_seq, row in enumerate(rows):
        tenant_id, seq, record_type, payload_json, prev_hash, record_hash = row
        if seq != expected_seq or prev_hash != expected_prev:
            return False, "sequence_or_predecessor_mismatch"
        try:
            expected_hash = independent_record_hash(
                tenant_id, seq, record_type, payload_json, prev_hash
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return False, "invalid_evidence_payload"
        if not isinstance(expected_hash, str) or record_hash != expected_hash:
            return False, "record_hash_mismatch"
        expected_prev = record_hash
    return True, "ok"


def _is_sha256(value):
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _has_only_digest_fields(payload):
    forbidden = {"task", "prompt", "api_key", "authorization", "secret", "token"}
    return not any(key.lower() in forbidden for key in payload)


def verify_isolated_run(
    tenant_id,
    run_id,
    expected_commit,
    *,
    db_path=None,
    expected_provider=None,
    expected_model=None,
    expected_agent_id=None,
    expected_capability=None,
):
    db_path = db_path or os.getenv("OLA_EG_DB_PATH", "ola.db")
    if not isinstance(expected_commit, str) or COMMIT_PATTERN.fullmatch(expected_commit) is None:
        return fail("expected_commit_must_be_full_40_character_sha")
    try:
        resolved = Path(db_path).resolve()
        connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT tenant_id, seq, record_type, payload_json, prev_hash, record_hash "
            "FROM evidence_records WHERE tenant_id=? ORDER BY seq",
            (tenant_id,),
        ).fetchall()
        connection.close()
    except (OSError, sqlite3.Error):
        return fail("evidence_database_unavailable")

    if not rows:
        return fail("tenant_evidence_chain_empty")
    chain_ok, chain_reason = verify_hash_chain(rows)
    if not chain_ok:
        return fail(chain_reason)

    run_rows = []
    for row in rows:
        try:
            payload = json.loads(row[3])
        except (TypeError, json.JSONDecodeError):
            return fail("invalid_evidence_payload")
        if isinstance(payload, dict) and payload.get("run_id") == run_id:
            run_rows.append((row[1], row[2], payload))

    if [item[1] for item in run_rows] != EXPECTED_EVENT_ORDER:
        return fail("isolated_run_lifecycle_missing_or_out_of_order")

    payloads = [item[2] for item in run_rows]
    for (_, record_type, payload) in run_rows:
        if payload.get(V2_KEY) != {
            "version": 2,
            "record_type": record_type,
            "producer": "ola_runtime",
        }:
            return fail("isolated_run_event_not_bound_to_runtime_producer")
        if not _has_only_digest_fields(payload):
            return fail("plaintext_or_secret_field_present_in_evidence")

    start, provider, worker_start, worker_end, end = payloads
    agent_id = start.get("agent_id")
    instance_id = start.get("agent_instance_id")
    capability = start.get("capability")
    specialist_role = start.get("specialist_role")
    execution_profile = start.get("execution_profile")

    if start.get("source_commit") != expected_commit:
        return fail("run_start_source_commit_mismatch")
    if start.get("execution_boundary") != "container":
        return fail("run_start_not_container_boundary")
    if not _is_sha256(start.get("task_digest")) or not _is_sha256(start.get("capability_input_digest")):
        return fail("run_start_input_commitment_invalid")
    if not isinstance(agent_id, str) or not isinstance(instance_id, str):
        return fail("run_start_agent_identity_missing")
    try:
        if str(uuid.UUID(instance_id)) != instance_id or uuid.UUID(instance_id).version != 4:
            return fail("agent_instance_id_not_uuid4")
    except (ValueError, TypeError, AttributeError):
        return fail("agent_instance_id_not_uuid4")
    if expected_agent_id is not None and agent_id != expected_agent_id:
        return fail("unexpected_agent_id")
    if expected_capability is not None and capability != expected_capability:
        return fail("unexpected_capability")

    if provider.get("agent_id") != agent_id or provider.get("agent_instance_id") != instance_id:
        return fail("provider_agent_identity_mismatch")
    provider_name = provider.get("provider")
    model = provider.get("model")
    if provider_name not in ("ollama", "openai") or not isinstance(model, str) or not model:
        return fail("provider_identity_missing")
    if start.get("provider") != provider_name:
        return fail("run_start_provider_mismatch")
    if expected_provider is not None and provider_name != expected_provider:
        return fail("unexpected_provider")
    if expected_model is not None and model != expected_model:
        return fail("unexpected_model")
    if provider_name == "ollama":
        model_digest = provider.get("model_digest")
        if not isinstance(model_digest, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", model_digest) is None:
            return fail("ollama_model_digest_invalid")
    elif provider.get("model_digest") is not None:
        return fail("hosted_model_digest_must_be_provider_managed")
    for field in ("prompt_digest", "schema_digest", "raw_response_digest",
                  "output_digest", "model_output_digest"):
        if not _is_sha256(provider.get(field)):
            return fail(f"provider_{field}_invalid")
    if provider.get("fallback_used") is not False or provider.get("model_output_role") != "advisory_only":
        return fail("provider_fallback_or_authority_violation")
    if not isinstance(provider.get("request_id"), str) or not provider["request_id"]:
        return fail("provider_request_id_missing")
    if type(provider.get("latency_ms")) is not int or provider["latency_ms"] < 0:
        return fail("provider_latency_invalid")

    for worker_event in (worker_start, worker_end):
        if (
            worker_event.get("agent_id") != agent_id
            or worker_event.get("agent_instance_id") != instance_id
            or worker_event.get("specialist_role") != specialist_role
            or worker_event.get("execution_profile") != execution_profile
            or worker_event.get("capability") != capability
            or worker_event.get("execution_boundary") != "container"
            or worker_event.get("source_commit") != expected_commit
            or worker_event.get("model_output_digest") != provider.get("model_output_digest")
        ):
            return fail("worker_identity_or_provenance_mismatch")
    if not isinstance(worker_start.get("image_digest"), str) or re.fullmatch(
        r"sha256:[a-f0-9]{64}", worker_start["image_digest"]
    ) is None:
        return fail("worker_image_digest_invalid")
    if worker_end.get("status") != "COMPLETED":
        return fail("worker_did_not_complete")
    if worker_end.get("image_digest") != worker_start.get("image_digest"):
        return fail("worker_image_changed_during_run")
    container_id = worker_end.get("container_id")
    if not isinstance(container_id, str) or CONTAINER_PATTERN.fullmatch(container_id) is None:
        return fail("worker_container_identity_invalid")
    if worker_end.get("worker_pid") != 1 or worker_end.get("exit_code") != 0:
        return fail("worker_process_boundary_or_exit_invalid")
    if not _is_sha256(worker_end.get("input_digest")) or not _is_sha256(worker_end.get("output_digest")):
        return fail("worker_input_or_output_digest_invalid")
    if worker_end.get("model_output_digest") != provider.get("model_output_digest"):
        return fail("worker_model_output_digest_mismatch")
    nonce = worker_end.get("worker_nonce")
    try:
        if not isinstance(nonce, str) or str(uuid.UUID(nonce)) != nonce or uuid.UUID(nonce).version != 4:
            return fail("worker_nonce_invalid")
    except (ValueError, TypeError, AttributeError):
        return fail("worker_nonce_invalid")

    if (
        end.get("status") != "COMPLETED"
        or end.get("source_commit") != expected_commit
        or end.get("execution_boundary") != "container"
        or end.get("agent_id") != agent_id
        or end.get("agent_instance_id") != instance_id
        or end.get("worker_count") != 1
        or end.get("container_id") != container_id
        or end.get("output_digest") != worker_end.get("output_digest")
        or end.get("model_output_digest") != provider.get("model_output_digest")
    ):
        return fail("run_end_does_not_match_worker_proof")

    return {
        "status": "VERIFIED",
        "run_id": run_id,
        "tenant_id": tenant_id,
        "source_commit": expected_commit,
        "agent_id": agent_id,
        "agent_instance_id": instance_id,
        "specialist_role": specialist_role,
        "execution_profile": execution_profile,
        "capability": capability,
        "provider": provider_name,
        "model": model,
        "model_digest": provider.get("model_digest"),
        "container_id": container_id,
        "worker_pid": worker_end["worker_pid"],
        "exit_code": worker_end["exit_code"],
        "output_digest": worker_end["output_digest"],
        "verified_evidence_events": EXPECTED_EVENT_ORDER,
    }


def main():
    parser = argparse.ArgumentParser(description="Independently verify one isolated OLA agent run.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--db-path", default=os.getenv("OLA_EG_DB_PATH", "ola.db"))
    parser.add_argument("--expected-provider")
    parser.add_argument("--expected-model")
    parser.add_argument("--expected-agent-id")
    parser.add_argument("--expected-capability")
    args = parser.parse_args()
    result = verify_isolated_run(
        args.tenant_id,
        args.run_id,
        args.expected_commit,
        db_path=args.db_path,
        expected_provider=args.expected_provider,
        expected_model=args.expected_model,
        expected_agent_id=args.expected_agent_id,
        expected_capability=args.expected_capability,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result.get("status") == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
