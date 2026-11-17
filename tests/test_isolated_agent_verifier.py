import json
import sqlite3
import uuid

from scripts.verify_isolated_agent_run import (
    GENESIS_HASH,
    V2_KEY,
    independent_record_hash,
    verify_isolated_run,
)


TENANT_ID = "tenant-isolated-proof"
RUN_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
WORKER_NONCE = str(uuid.uuid4())
COMMIT = "a" * 40
IMAGE_DIGEST = "sha256:" + "1" * 64
CONTAINER_ID = "2" * 64
MODEL_OUTPUT_DIGEST = "f" * 64
OUTPUT_DIGEST = "4" * 64


def _events():
    common = {
        "run_id": RUN_ID,
        "agent_id": "hermes-001",
        "agent_instance_id": INSTANCE_ID,
        "specialist_role": "Hermes",
        "execution_profile": "react",
        "capability": "tool.safe_expression",
    }
    return [
        ("execution.run.start", {
            **common,
            "source_commit": COMMIT,
            "execution_boundary": "container",
            "task_digest": "5" * 64,
            "capability_input_digest": "6" * 64,
            "provider": "ollama",
        }),
        ("agent.provider.response", {
            "run_id": RUN_ID,
            "agent_id": "hermes-001",
            "agent_instance_id": INSTANCE_ID,
            "provider": "ollama",
            "model": "qwen2.5:0.5b-instruct",
            "model_digest": "sha256:" + "a" * 64,
            "request_id": "ollama-request-001",
            "prompt_digest": "b" * 64,
            "schema_digest": "c" * 64,
            "raw_response_digest": "d" * 64,
            "output_digest": "e" * 64,
            "model_output_digest": MODEL_OUTPUT_DIGEST,
            "latency_ms": 12,
            "fallback_used": False,
            "model_output_role": "advisory_only",
        }),
        ("agent.worker.start", {
            **common,
            "execution_boundary": "container",
            "source_commit": COMMIT,
            "image_digest": IMAGE_DIGEST,
            "model_output_digest": MODEL_OUTPUT_DIGEST,
        }),
        ("agent.worker.end", {
            **common,
            "execution_boundary": "container",
            "source_commit": COMMIT,
            "status": "COMPLETED",
            "reason": None,
            "container_id": CONTAINER_ID,
            "image_digest": IMAGE_DIGEST,
            "worker_pid": 1,
            "exit_code": 0,
            "worker_nonce": WORKER_NONCE,
            "input_digest": "3" * 64,
            "model_output_digest": MODEL_OUTPUT_DIGEST,
            "output_digest": OUTPUT_DIGEST,
        }),
        ("execution.run.end", {
            **common,
            "status": "COMPLETED",
            "reason": None,
            "source_commit": COMMIT,
            "execution_boundary": "container",
            "worker_count": 1,
            "container_id": CONTAINER_ID,
            "output_digest": OUTPUT_DIGEST,
            "model_output_digest": MODEL_OUTPUT_DIGEST,
        }),
    ]


def _create_database(path, events=None):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE evidence_records ("
        "tenant_id TEXT, seq INTEGER, record_type TEXT, payload_json TEXT, "
        "prev_hash TEXT, record_hash TEXT)"
    )
    previous = GENESIS_HASH
    for seq, (record_type, payload) in enumerate(events or _events()):
        sealed = {
            **payload,
            V2_KEY: {
                "version": 2,
                "record_type": record_type,
                "producer": "ola_runtime",
            },
        }
        payload_json = json.dumps(
            sealed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        record_hash = independent_record_hash(
            TENANT_ID, seq, record_type, payload_json, previous
        )
        connection.execute(
            "INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?)",
            (TENANT_ID, seq, record_type, payload_json, previous, record_hash),
        )
        previous = record_hash
    connection.commit()
    connection.close()


def test_independent_verifier_accepts_valid_isolated_worker_lifecycle(tmp_path):
    db_path = tmp_path / "evidence.db"
    _create_database(db_path)

    result = verify_isolated_run(
        TENANT_ID,
        RUN_ID,
        COMMIT,
        db_path=str(db_path),
        expected_provider="ollama",
        expected_model="qwen2.5:0.5b-instruct",
        expected_agent_id="hermes-001",
        expected_capability="tool.safe_expression",
    )

    assert result["status"] == "VERIFIED"
    assert result["worker_pid"] == 1
    assert result["exit_code"] == 0
    assert result["container_id"] == CONTAINER_ID
    assert result["verified_evidence_events"] == [
        "execution.run.start",
        "agent.provider.response",
        "agent.worker.start",
        "agent.worker.end",
        "execution.run.end",
    ]


def test_independent_verifier_rejects_tampered_hash_chain(tmp_path):
    db_path = tmp_path / "evidence.db"
    _create_database(db_path)
    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT payload_json FROM evidence_records WHERE seq=3"
    ).fetchone()
    payload = json.loads(row[0])
    payload["worker_pid"] = 999
    connection.execute(
        "UPDATE evidence_records SET payload_json=? WHERE seq=3",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
    )
    connection.commit()
    connection.close()

    result = verify_isolated_run(TENANT_ID, RUN_ID, COMMIT, db_path=str(db_path))

    assert result["status"] == "BLOCK"
    assert result["reason"] == "record_hash_mismatch"


def test_independent_verifier_rejects_validly_hashed_but_unsafe_worker_proof(tmp_path):
    db_path = tmp_path / "evidence.db"
    events = _events()
    worker_end = dict(events[3][1])
    worker_end["worker_pid"] = 999
    events[3] = (events[3][0], worker_end)
    _create_database(db_path, events)

    result = verify_isolated_run(TENANT_ID, RUN_ID, COMMIT, db_path=str(db_path))

    assert result["status"] == "BLOCK"
    assert result["reason"] == "worker_process_boundary_or_exit_invalid"


def test_independent_verifier_rejects_out_of_order_lifecycle(tmp_path):
    db_path = tmp_path / "evidence.db"
    events = _events()
    events[1], events[2] = events[2], events[1]
    _create_database(db_path, events)

    result = verify_isolated_run(TENANT_ID, RUN_ID, COMMIT, db_path=str(db_path))

    assert result["status"] == "BLOCK"
    assert result["reason"] == "isolated_run_lifecycle_missing_or_out_of_order"
