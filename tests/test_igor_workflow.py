import hashlib
import json

from app.hashchain import canonical_json, compute_record_hash, compute_record_hash_v2, sealed_payload_json, EVIDENCE_META_KEY
from app.igor_workflow import verify_dag_records
from app.workflow_engine import WorkflowEngine, validate_plan


def proof():
    events = [{
        "event": "execution.run.start",
        "run_id": "run1",
        "task_digest": hashlib.sha256(b"test").hexdigest(),
        "allowed_tools": ["llm_agent", "safe_expression"],
        "source_commit": "expected",
        "requester_id": "person1",
        "commit": "expected",
    }]
    nodes = validate_plan({"nodes": [
        {"id": "alpha", "tool": "llm_agent", "task": "one", "needs": []},
        {"id": "beta", "tool": "llm_agent", "task": "two", "needs": []},
        {"id": "join", "tool": "safe_expression", "task": "2+2", "needs": ["alpha", "beta"]},
    ]}, allowed_tools={"llm_agent", "safe_expression"})
    def execute(node, deps):
        if node.tool == "llm_agent":
            return {"output": node.id, "provider": "ollama", "model": "qwen", "response_id": node.id}
        return "4"
    WorkflowEngine(max_workers=2).run(nodes, execute,
        lambda event: events.append({**event, "requester_id": "person1",
                                     "planner": {"response_id": "p1"}, "commit": "expected",
                                     "task_digest": hashlib.sha256(b"test").hexdigest(),
                                     "allowed_tools": ["llm_agent", "safe_expression"]}),
        run_id="run1")
    events.append({
        "event": "execution.run.end",
        "run_id": "run1",
        "status": "COMPLETED",
        "workflow_status": "COMPLETED_UNVERIFIED",
        "pre_end_igor_status": "VERIFIED",
        "task_digest": hashlib.sha256(b"test").hexdigest(),
        "completed_node_count": 3,
        "failed_node_count": 0,
        "skipped_node_count": 0,
        "source_commit": "expected",
        "requester_id": "person1",
        "commit": "expected",
    })
    return rehash(events)


def rehash(events):
    records = []
    prev = "0" * 64
    for seq, event in enumerate(events):
        event = dict(event)
        event.pop(EVIDENCE_META_KEY, None)
        producer = "tenant_api" if event["event"] == "customer.proof" else "ola_runtime"
        raw = sealed_payload_json(event["event"], event, producer=producer)
        current = compute_record_hash_v2("tenant", seq, prev, event["event"], producer, raw)
        records.append({"tenant_id": "tenant", "seq": seq, "prev_hash": prev,
                        "record_hash": current, "record_type": event["event"], "payload_json": raw})
        prev = current
    return records


def check(records, **kwargs):
    return verify_dag_records(records, tenant_id="tenant", run_id="run1",
                              expected_commit="expected", **kwargs)


def test_standalone_verifier_recomputes_full_trace():
    report = check(proof())
    assert report["status"] == "VERIFIED", report
    assert report["verified_nodes"] == 3
    assert report["report_digest"]


def test_tamper_breaks_chain_even_when_execution_claims_success():
    evidence = proof()
    evidence[2]["payload_json"] = "{}"
    assert check(evidence)["status"] == "BLOCK"


def test_missing_terminal_is_blocked():
    events = [json.loads(row["payload_json"]) for row in proof()]
    events = [event for event in events if event["event"] != "workflow.completed"]
    assert check(rehash(events))["status"] == "BLOCK"


def test_igor_requires_exactly_one_ordered_execution_lifecycle():
    events = [json.loads(row["payload_json"]) for row in proof()]
    events.pop(0)
    assert check(rehash(events))["status"] == "BLOCK"

    events = [json.loads(row["payload_json"]) for row in proof()]
    events.pop()
    assert check(rehash(events))["status"] == "BLOCK"

    events = [json.loads(row["payload_json"]) for row in proof()]
    end = events.pop()
    events.insert(2, end)
    assert check(rehash(events))["status"] == "BLOCK"

    events = [json.loads(row["payload_json"]) for row in proof()]
    events.insert(1, dict(events[0]))
    assert check(rehash(events))["status"] == "BLOCK"


def test_fake_timing_rejected_even_after_rehash():
    events = [json.loads(row["payload_json"]) for row in proof()]
    for event in events:
        if event["event"] == "task.completed":
            event["worker_finished_ns"] = event["worker_started_ns"]
    assert check(rehash(events))["status"] == "BLOCK"


def test_goal_digest_mismatch_between_lifecycle_and_plan_is_blocked():
    events = [json.loads(row["payload_json"]) for row in proof()]
    planned = next(event for event in events if event["event"] == "workflow.planned")
    planned["task_digest"] = "0" * 64
    assert check(rehash(events))["status"] == "BLOCK"


def test_igor_rejects_unsupported_capability_even_if_allowlist_claims_it():
    from app.workflow_engine import _digest

    events = [json.loads(row["payload_json"]) for row in proof()]
    for event in events:
        if event.get("run_id") == "run1" and "allowed_tools" in event:
            event["allowed_tools"] = sorted(set(event["allowed_tools"] + ["shell"]))
    planned = next(event for event in events if event["event"] == "workflow.planned")
    planned["nodes"][0]["tool"] = "shell"
    planned["plan_digest"] = _digest(planned["nodes"])
    assert check(rehash(events))["status"] == "BLOCK"


def test_igor_blocks_unallowlisted_plan_tool_even_with_recomputed_digest():
    from app.workflow_engine import _digest

    events = [json.loads(row["payload_json"]) for row in proof()]
    planned = next(event for event in events if event["event"] == "workflow.planned")
    planned["nodes"][0]["tool"] = "shell"
    planned["plan_digest"] = _digest(planned["nodes"])
    assert check(rehash(events))["status"] == "BLOCK"


def test_wrong_commit_and_missing_run_block():
    assert verify_dag_records(proof(), tenant_id="tenant", run_id="run1",
                              expected_commit="wrong")["status"] == "BLOCK"
    assert verify_dag_records(proof(), tenant_id="tenant", run_id="other")["status"] == "UNKNOWN"


def test_missing_node_or_duplicate_response_rejected():
    events = [json.loads(row["payload_json"]) for row in proof()]
    values = [e for e in events if e["event"] == "task.completed" and isinstance(e["output"], dict)]
    values[1]["output"]["response_id"] = values[0]["output"]["response_id"]
    from app.workflow_engine import _digest
    values[1]["output_digest"] = _digest(values[1]["output"])
    assert check(rehash(events))["status"] == "BLOCK"

def test_customer_evidence_with_matching_run_id_does_not_poison_dag_verification():
    # The full tenant chain includes customer evidence, but only trusted
    # workflow/task record types belong to the NINA execution trace.
    events = [json.loads(row["payload_json"]) for row in proof()]
    events.insert(-1, {"event": "customer.proof", "run_id": "run1",
                       "note": "unrelated user evidence"})
    report = check(rehash(events))
    assert report["status"] == "VERIFIED", report
    assert report["evidence_count"] == sum(
        event["event"].startswith(("workflow.", "task.")) for event in events
    )


def test_unexpected_internal_workflow_event_remains_blocked():
    events = [json.loads(row["payload_json"]) for row in proof()]
    events.insert(-1, {"event": "workflow.unexpected", "run_id": "run1",
                       "requester_id": "person1", "planner": {"response_id": "p1"},
                       "commit": "expected"})
    assert check(rehash(events))["status"] == "BLOCK"


def test_v1_forged_customer_trace_never_promotes_to_trusted_workflow():
    legacy = []
    prev = "0" * 64
    for seq, row in enumerate(proof()):
        payload = json.loads(row["payload_json"])
        payload.pop(EVIDENCE_META_KEY)
        raw = canonical_json(payload)
        digest = compute_record_hash("tenant", seq, prev, raw)
        legacy.append({**row, "seq": seq, "prev_hash": prev,
                       "record_hash": digest, "payload_json": raw})
        prev = digest
    assert check(legacy)["status"] == "BLOCK"


def test_v2_type_tamper_is_detected_even_when_hash_is_unchanged():
    from app.hashchain import verify_chain
    forged = proof()
    forged[0]["record_type"] = "customer.proof"
    assert verify_chain(forged) == (False, "record type or producer binding mismatch")
    assert check(forged)["status"] == "BLOCK"


def sandbox_events(node_count=1):
    source = "print(42)"
    task = json.dumps({"operation": "python_exec", "source": source}, separators=(",", ":"))
    output = {
        "executor": "vercel_sandbox",
        "operation": "python_exec",
        "runtime": "python3.14",
        "sandbox_name": "sandbox-run-123",
        "image": "vercel/sandbox/python@sha256:e678419c0a4463c1f892b44f6f115c3bd8f5ac3f7817841dd5709947e4ed53e8",
        "region": "fra1",
        "network_policy": "deny-all",
        "persistent": False,
        "destroy_on_exit": True,
        "resources": {"vcpus": 1, "memory_mb": 2048},
        "timeout_seconds": 30,
        "output_limit_bytes_per_stream": 8192,
        "source_bytes": len(source.encode("utf-8")),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "exit_code": 0,
        "stdout": "42\\n",
        "stderr": "",
        "stdout_sha256": hashlib.sha256(b"42\\n").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    nodes = validate_plan({"nodes": [
        {"id": f"sandbox-{index}", "tool": "vercel_sandbox", "task": task, "needs": []}
        for index in range(node_count)
    ]}, allowed_tools={"vercel_sandbox"})
    events = [{
        "event": "execution.run.start",
        "run_id": "sandbox-run",
        "task_digest": hashlib.sha256(b"sandbox").hexdigest(),
        "allowed_tools": ["vercel_sandbox"],
        "source_commit": "expected",
        "requester_id": "person1",
        "commit": "expected",
    }]
    WorkflowEngine(max_workers=max(1, node_count)).run(
        nodes,
        lambda node, deps: output,
        lambda event: events.append({**event, "requester_id": "person1",
                                     "planner": {"response_id": "p1"}, "commit": "expected",
                                     "task_digest": hashlib.sha256(b"sandbox").hexdigest(),
                                     "allowed_tools": ["vercel_sandbox"]}),
        run_id="sandbox-run",
    )
    events.append({
        "event": "execution.run.end",
        "run_id": "sandbox-run",
        "status": "COMPLETED",
        "workflow_status": "COMPLETED_UNVERIFIED",
        "pre_end_igor_status": "VERIFIED",
        "task_digest": hashlib.sha256(b"sandbox").hexdigest(),
        "completed_node_count": node_count,
        "failed_node_count": 0,
        "skipped_node_count": 0,
        "source_commit": "expected",
        "requester_id": "person1",
        "commit": "expected",
    })
    return events


def verify_sandbox_events(events):
    return verify_dag_records(rehash(events), tenant_id="tenant", run_id="sandbox-run",
                              expected_commit="expected")


def test_igor_verifies_sandbox_execution_shape_and_source_digest():
    report = verify_sandbox_events(sandbox_events())
    assert report["status"] == "VERIFIED", report
    assert report["trust_scope"] == "LOCAL_HASH_CHAIN_AND_CAPTURED_RUNTIME_EVENTS"
    assert report["external_attestation"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("field,value", [
    ("region", "iad1"),
    ("network_policy", "allow-all"),
    ("persistent", True),
    ("destroy_on_exit", False),
    ("resources", {"vcpus": 2, "memory_mb": 4096}),
    ("timeout_seconds", 61),
    ("output_limit_bytes_per_stream", 8193),
    ("source_bytes", 1),
])
def test_igor_blocks_sandbox_policy_mutations(field, value):
    events = sandbox_events()
    completed = next(event for event in events if event["event"] == "task.completed")
    completed["output"][field] = value
    assert verify_sandbox_events(rehash(events))["status"] == "BLOCK"


def test_igor_rejects_sandbox_unpinned_runtime_image_even_with_valid_chain():
    from app.workflow_engine import _digest

    events = sandbox_events()
    completed = next(event for event in events if event["event"] == "task.completed")
    completed["output"]["image"] = "vercel/sandbox/python:3.14"
    completed["output_digest"] = _digest(completed["output"])
    report = verify_sandbox_events(events)
    assert report["status"] == "BLOCK"
    assert "image" in report["reason"]


def test_igor_rejects_other_digest_pinned_sandbox_image():
    from app.workflow_engine import _digest

    events = sandbox_events()
    completed = next(event for event in events if event["event"] == "task.completed")
    completed["output"]["image"] = "vercel/sandbox/python@sha256:" + "b" * 64
    completed["output_digest"] = _digest(completed["output"])
    report = verify_sandbox_events(events)
    assert report["status"] == "BLOCK"
    assert "allowlisted runtime image" in report["reason"]


def test_igor_rejects_sandbox_output_digest_mismatch_even_with_valid_chain():
    from app.workflow_engine import _digest

    events = sandbox_events()
    completed = next(event for event in events if event["event"] == "task.completed")
    completed["output"]["stdout_sha256"] = "0" * 64
    completed["output_digest"] = _digest(completed["output"])
    report = verify_sandbox_events(events)
    assert report["status"] == "BLOCK"


def test_igor_rejects_sandbox_nonzero_exit_code():
    from app.workflow_engine import _digest

    events = sandbox_events()
    completed = next(event for event in events if event["event"] == "task.completed")
    completed["output"]["exit_code"] = 2
    completed["output_digest"] = _digest(completed["output"])
    report = verify_sandbox_events(events)
    assert report["status"] == "BLOCK"


def test_igor_rejects_replayed_sandbox_identity_within_one_run():
    report = verify_sandbox_events(sandbox_events(node_count=2))
    assert report["status"] == "BLOCK"
    assert "identity replayed" in report["reason"]
