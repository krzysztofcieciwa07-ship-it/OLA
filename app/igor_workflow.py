"""Independent DAG verifier: no calls to NINA planner, scheduler, or executor.

Certifies integrity/consistency of *captured* local events, not an external
attestation that requests were truly handled by the named LLM provider.
"""
import hashlib
import json

from .igor_evidence_verifier import verify_chain, trusted_record


EXPECTED_VERCEL_SANDBOX_IMAGE = "vercel/sandbox/python@sha256:e678419c0a4463c1f892b44f6f115c3bd8f5ac3f7817841dd5709947e4ed53e8"
EXPECTED_VERCEL_SANDBOX_REGION = "fra1"
SUPPORTED_WORKFLOW_TOOLS = frozenset({
    "safe_expression", "local_mcp_tool_registry.sha256", "llm_agent", "vercel_sandbox",
    "retro.linear.read", "retro.slack.read", "retro.synthesize", "retro.render",
    "support.intercom.read", "support.repro.isolated", "support.code.search",
    "support.jira.draft",
})


def _hash(value):
    material = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode()).hexdigest()


def _result(status, reason, **kw):
    return {"status": status, "reason": reason, **kw}




def _verify_sandbox_output(node, output):
    """Independently validate captured Sandbox result fields, not provider attestation."""
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    try:
        task = json.loads(node["task"], object_pairs_hook=unique_object)
    except (TypeError, ValueError):
        return "sandbox task envelope malformed"
    if (not isinstance(task, dict) or set(task) != {"operation", "source"}
            or task.get("operation") != "python_exec"
            or not isinstance(task.get("source"), str) or not task["source"].strip()):
        return "sandbox task contract invalid"
    if len(task["source"].encode("utf-8")) > 100_000:
        return "sandbox source exceeds policy"

    required = {
        "executor", "operation", "runtime", "sandbox_name", "image", "region",
        "failover_regions", "network_policy", "persistent", "destroy_on_exit", "resources", "timeout_seconds",
        "output_limit_bytes_per_stream", "source_bytes", "source_sha256",
        "exit_code", "stdout", "stderr", "stdout_sha256", "stderr_sha256",
        "stdout_truncated", "stderr_truncated",
    }
    if not isinstance(output, dict) or set(output) != required:
        return "sandbox output schema invalid"
    if (output.get("executor") != "vercel_sandbox"
            or output.get("operation") != "python_exec"
            or output.get("runtime") != "python3"):
        return "sandbox executor provenance invalid"
    if not isinstance(output.get("sandbox_name"), str) or not output["sandbox_name"]:
        return "sandbox identity missing"
    if output.get("region") != EXPECTED_VERCEL_SANDBOX_REGION:
        return "sandbox region is not the approved EU region"
    if output.get("failover_regions") != []:
        return "sandbox failover regions are not disabled"
    if output.get("network_policy") != "deny-all":
        return "sandbox network policy is not deny-all"
    if type(output.get("persistent")) is not bool or output["persistent"] is not False:
        return "sandbox persistence policy invalid"
    if type(output.get("destroy_on_exit")) is not bool or output["destroy_on_exit"] is not True:
        return "sandbox cleanup policy invalid"
    resources = output.get("resources")
    if (not isinstance(resources, dict) or set(resources) != {"vcpus", "memory_mb"}
            or type(resources.get("vcpus")) is not int or resources.get("vcpus") != 1
            or type(resources.get("memory_mb")) is not int or resources.get("memory_mb") != 2048):
        return "sandbox resource policy invalid"
    if (type(output.get("timeout_seconds")) is not int
            or not 1 <= output["timeout_seconds"] <= 60):
        return "sandbox execution timeout invalid"
    if (type(output.get("output_limit_bytes_per_stream")) is not int
            or not 1 <= output["output_limit_bytes_per_stream"] <= 3072):
        return "sandbox output budget invalid"
    if type(output.get("source_bytes")) is not int:
        return "sandbox source size invalid"
    image = output.get("image")
    if not isinstance(image, str):
        return "sandbox image missing"
    prefix, marker, image_digest = image.rpartition("@sha256:")
    if (not prefix or not marker or len(image_digest) != 64
            or any(char not in "0123456789abcdef" for char in image_digest)):
        return "sandbox image is not digest-pinned"
    if image != EXPECTED_VERCEL_SANDBOX_IMAGE:
        return "sandbox image does not match allowlisted runtime image"
    if type(output.get("exit_code")) is not int:
        return "sandbox exit code invalid"
    if type(output.get("stdout_truncated")) is not bool or type(output.get("stderr_truncated")) is not bool:
        return "sandbox output truncation flags invalid"
    if output["stdout_truncated"] or output["stderr_truncated"]:
        return "sandbox output truncated"

    for stream in ("stdout", "stderr"):
        value = output.get(stream)
        digest = output.get(stream + "_sha256")
        if (not isinstance(value, str)
                or len(value.encode("utf-8")) > output["output_limit_bytes_per_stream"]):
            return "sandbox captured output invalid"
        expected = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if not isinstance(digest, str) or digest != expected:
            return "sandbox captured output digest mismatch"

    source_bytes = task["source"].encode("utf-8")
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    if output["source_bytes"] != len(source_bytes):
        return "sandbox source byte count mismatch"
    if output.get("source_sha256") != source_digest:
        return "sandbox source digest mismatch"
    if output["exit_code"] != 0:
        return "sandbox process exited nonzero"
    return None


def verify_dag_records(records, *, tenant_id, run_id, expected_commit=None,
                       require_overlap=False, expected_provider=None, require_lifecycle=True):
    if not records:
        return _result("UNKNOWN", "no tenant evidence")
    try:
        if any(row.get("tenant_id") != tenant_id for row in records):
            return _result("BLOCK", "tenant provenance mismatch")
        chain_ok, chain_reason = verify_chain(records)
        if not chain_ok:
            return _result("BLOCK", "tenant chain " + chain_reason)
        relevant = []
        relevant_rows = []
        lifecycle = {"execution.run.start": [], "execution.run.end": []}
        for row in records:
            record_type = row["record_type"]
            if record_type in lifecycle:
                payload = json.loads(row["payload_json"])
                if not isinstance(payload, dict):
                    return _result("BLOCK", "execution lifecycle payload is not an object")
                if payload.get("run_id") == run_id:
                    if not trusted_record(row):
                        return _result("BLOCK", "legacy or untrusted execution lifecycle producer")
                    lifecycle[record_type].append((row, payload))
                continue
            # Validate the complete hash chain, but never parse untrusted
            # customer payload shapes as privileged workflow trace events.
            if not record_type.startswith(("workflow.", "task.")):
                continue
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                return _result("BLOCK", "trusted workflow event is not an object")
            if payload.get("run_id") == run_id:
                if not trusted_record(row):
                    return _result("BLOCK", "legacy or untrusted workflow producer")
                if payload.get("event") != record_type:
                    return _result("BLOCK", "event type mismatch")
                relevant.append(payload)
                relevant_rows.append(row)
        if not relevant:
            if any(lifecycle.values()):
                return _result("BLOCK", "execution lifecycle exists without workflow trace")
            return _result("UNKNOWN", "run evidence missing")
        if len(lifecycle["execution.run.start"]) != 1:
            return _result("BLOCK", "run must have exactly one durable start record")
        if len(lifecycle["execution.run.end"]) > 1:
            return _result("BLOCK", "run has duplicate terminal lifecycle records")
        if require_lifecycle and len(lifecycle["execution.run.end"]) != 1:
            return _result("BLOCK", "run is missing its durable end record")

        start_row, start_payload = lifecycle["execution.run.start"][0]
        task_digest = start_payload.get("task_digest")
        allowed_tools = start_payload.get("allowed_tools")
        if (not isinstance(allowed_tools, list) or not allowed_tools or len(allowed_tools) > 16
                or not all(isinstance(tool, str) and tool.strip() for tool in allowed_tools)
                or len(set(allowed_tools)) != len(allowed_tools)
                or allowed_tools != sorted(allowed_tools)
                or not set(allowed_tools) <= SUPPORTED_WORKFLOW_TOOLS):
            return _result("BLOCK", "execution start capability allowlist invalid")
        if (not isinstance(task_digest, str) or len(task_digest) != 64
                or any(char not in "0123456789abcdef" for char in task_digest)):
            return _result("BLOCK", "execution start task digest invalid")
        plan_row = relevant_rows[0]
        if records.index(start_row) >= records.index(plan_row):
            return _result("BLOCK", "execution start must precede workflow plan")
        plan_event = relevant[0]
        if (start_payload.get("requester_id") != plan_event.get("requester_id")
                or start_payload.get("source_commit") != plan_event.get("commit")
                or start_payload.get("commit") != plan_event.get("commit")
                or plan_event.get("task_digest") != task_digest
                or plan_event.get("allowed_tools") != allowed_tools):
            return _result("BLOCK", "execution start provenance mismatch")
        if plan_event.get("event") != "workflow.planned":
            return _result("BLOCK", "missing plan")
        plan = plan_event.get("nodes")
        if not isinstance(plan, list) or not 1 <= len(plan) <= 16 or _hash(plan) != plan_event.get("plan_digest"):
            return _result("BLOCK", "invalid plan digest or size")
        nodes = {}
        for node in plan:
            if not isinstance(node, dict) or set(node) != {"id", "tool", "task", "needs"}:
                return _result("BLOCK", "malformed DAG node")
            nid, needs = node["id"], node["needs"]
            if not isinstance(nid, str) or nid in nodes or not isinstance(needs, list):
                return _result("BLOCK", "duplicate node or invalid dependencies")
            if not isinstance(node["tool"], str) or not isinstance(node["task"], str):
                return _result("BLOCK", "malformed DAG tool/task")
            if node["tool"] not in allowed_tools:
                return _result("BLOCK", "DAG node tool outside recorded capability allowlist")
            if any(not isinstance(dep, str) for dep in needs) or len(set(needs)) != len(needs):
                return _result("BLOCK", "invalid dependency list")
            nodes[nid] = node
        if any(dep not in nodes or dep == nid for nid, node in nodes.items() for dep in node["needs"]):
            return _result("BLOCK", "unresolvable dependencies")
        starts, finishes, response_ids, sandbox_names = {}, {}, set(), set()
        terminal = None
        for index, event in enumerate(relevant):
            if event.get("requester_id") != plan_event.get("requester_id"):
                return _result("BLOCK", "requester mismatch")
            if event.get("planner") != plan_event.get("planner"):
                return _result("BLOCK", "planner provenance mismatch")
            if event.get("commit") != plan_event.get("commit"):
                return _result("BLOCK", "run commit mismatch")
            if event.get("task_digest") != task_digest:
                return _result("BLOCK", "run task digest mismatch")
            if event.get("allowed_tools") != allowed_tools:
                return _result("BLOCK", "run capability allowlist mismatch")
            if expected_commit and event.get("commit") != expected_commit:
                return _result("BLOCK", "expected commit mismatch")
            if index == 0:
                continue
            if terminal is not None:
                return _result("BLOCK", "event after terminal state")
            kind, nid = event.get("event"), event.get("node_id")
            if kind == "task.started":
                if nid not in nodes or nid in starts:
                    return _result("BLOCK", "unknown or duplicate task start")
                if any(dep not in finishes for dep in nodes[nid]["needs"]):
                    return _result("BLOCK", "dependency not completed before start")
                deps = {dep: finishes[dep]["output"] for dep in nodes[nid]["needs"]}
                if event.get("input_digest") != _hash({"task": nodes[nid]["task"], "deps": deps}):
                    return _result("BLOCK", "input digest mismatch")
                starts[nid] = event
            elif kind == "task.completed":
                if nid not in starts or nid in finishes:
                    return _result("BLOCK", "completion without unique start")
                if _hash(event.get("output")) != event.get("output_digest"):
                    return _result("BLOCK", "output digest mismatch")
                begun, ended = event.get("worker_started_ns"), event.get("worker_finished_ns")
                if (not isinstance(begun, int) or isinstance(begun, bool)
                        or not isinstance(ended, int) or isinstance(ended, bool)
                        or begun >= ended):
                    return _result("BLOCK", "missing or invalid measured worker interval")
                if nodes[nid]["tool"] == "llm_agent":
                    output = event.get("output")
                    if (not isinstance(output, dict) or not all(
                            isinstance(output.get(key), str) and bool(output[key])
                            for key in ("output", "provider", "model", "response_id"))):
                        return _result("BLOCK", "LLM provenance missing")
                    if expected_provider and output["provider"] != expected_provider:
                        return _result("BLOCK", "LLM provider mismatch")
                    if output["response_id"] in response_ids:
                        return _result("BLOCK", "duplicate LLM response ID")
                    response_ids.add(output["response_id"])
                if nodes[nid]["tool"] == "vercel_sandbox":
                    sandbox_error = _verify_sandbox_output(nodes[nid], event.get("output"))
                    if sandbox_error:
                        return _result("BLOCK", sandbox_error)
                    sandbox_name = event["output"]["sandbox_name"]
                    if sandbox_name in sandbox_names:
                        return _result("BLOCK", "sandbox identity replayed within run")
                    sandbox_names.add(sandbox_name)
                finishes[nid] = event
            elif kind in ("workflow.completed", "workflow.failed"):
                if index != len(relevant) - 1:
                    return _result("BLOCK", "early terminal state")
                terminal = event
            else:
                return _result("BLOCK", "unexpected event")
        if terminal is None or terminal["event"] != "workflow.completed":
            return _result("BLOCK", "workflow did not complete")
        if (set(starts) != set(nodes) or set(finishes) != set(nodes)
                or terminal.get("status") != "COMPLETED_UNVERIFIED"
                or terminal.get("completed") != sorted(nodes)
                or terminal.get("failed") != {} or terminal.get("skipped") != []):
            return _result("BLOCK", "terminal summary mismatch or incomplete nodes")

        if require_lifecycle:
            end_row, end_payload = lifecycle["execution.run.end"][0]
            terminal_row = relevant_rows[-1]
            if records.index(end_row) <= records.index(terminal_row):
                return _result("BLOCK", "execution end must follow workflow terminal event")
            if (end_payload.get("task_digest") != task_digest
                    or end_payload.get("allowed_tools") != allowed_tools
                    or end_payload.get("source_commit") != plan_event.get("commit")
                    or end_payload.get("commit") != plan_event.get("commit")
                    or end_payload.get("requester_id") != plan_event.get("requester_id")):
                return _result("BLOCK", "execution end provenance mismatch")
            if (end_payload.get("workflow_status") != terminal.get("status")
                    or end_payload.get("status") != "COMPLETED"
                    or end_payload.get("pre_end_igor_status") != "VERIFIED"):
                return _result("BLOCK", "execution end status or pre-end verification mismatch")
            expected_counts = {
                "completed_node_count": len(finishes),
                "failed_node_count": len(terminal.get("failed", {})),
                "skipped_node_count": len(terminal.get("skipped", [])),
            }
            if any(type(end_payload.get(key)) is not int or end_payload.get(key) != value
                   for key, value in expected_counts.items()):
                return _result("BLOCK", "execution end node counts mismatch")
        overlap = 0
        llm_ids = [nid for nid, node in nodes.items() if node["tool"] == "llm_agent"]
        for index, a in enumerate(llm_ids):
            for b in llm_ids[index+1:]:
                if a in nodes[b]["needs"] or b in nodes[a]["needs"]:
                    continue
                left, right = finishes[a], finishes[b]
                overlap = max(overlap, min(left["worker_finished_ns"], right["worker_finished_ns"])
                              - max(left["worker_started_ns"], right["worker_started_ns"]))
        if require_overlap and overlap <= 0:
            return _result("BLOCK", "real LLM execution intervals did not overlap", overlap_ns=overlap)
        chain_tip = records[-1]["record_hash"]
        report_digest = _hash({"tenant_id": tenant_id, "run_id": run_id, "chain_tip": chain_tip,
                               "plan_digest": plan_event["plan_digest"], "completed": sorted(finishes),
                               "overlap_ns": overlap})
        return _result("VERIFIED", "captured DAG events and full tenant chain consistent",
                       verified_nodes=len(finishes), evidence_count=len(relevant),
                       chain_tip=chain_tip, plan_digest=plan_event["plan_digest"],
                       overlap_ns=overlap, report_digest=report_digest,
                       trust_scope="LOCAL_HASH_CHAIN_AND_CAPTURED_RUNTIME_EVENTS",
                       **({"external_attestation": "NOT_ESTABLISHED"}
                          if any(node.get("tool") == "vercel_sandbox" for node in plan)
                          else {}))
    except (TypeError, KeyError, ValueError, IndexError, AttributeError, OverflowError):
        return _result("BLOCK", "malformed evidence")
