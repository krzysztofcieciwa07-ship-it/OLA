"""Feature-gated autonomous workflow planning for the existing NINA runtime.

No implicit deterministic fallback: planning requires a real configured LLM.
All executable capabilities are already allowlisted by NINA.
"""
import json
import os
import uuid

from .workflow_engine import WorkflowEngine, WorkflowPlanError, validate_plan, _digest


def _unique_json_object(pairs):
    """Reject duplicate JSON members at every object depth."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def model_plan(goal, tools, *, independent_only=False):
    from .agent_runtime import _invoke_llm

    if not isinstance(goal, str) or not goal.strip() or len(goal) > 2000:
        raise WorkflowPlanError("invalid goal")
    contract = (
        'Respond with ONLY JSON: {"nodes":[{"id":"short_unique_id",'
        '"tool":"one_allowed_tool","task":"bounded instruction",'
        '"needs":[]}]}. Generate 1 to 16 useful nodes. '
        'Use dependencies only when needed and parallel independent work. '
        'Every needs entry MUST match an actual id of another node in the '
        'same plan; for independent nodes use needs:[]. '
        'No code fences, no prose. Never request tools outside allowed_tools.'
        ' For vercel_sandbox, task MUST be a JSON string containing exactly '
        '{"operation":"python_exec","source":"..."}; do not request a shell, '
        'arbitrary executable, network access, or extra task fields.'
    )
    if independent_only:
        contract += (
            " The user needs independent work only: create TWO to FOUR "
            "independent llm_agent nodes with needs:[] for every node. "
            "Choose the node identities and the substantive tasks yourself. "
            "Do not create imaginary dependencies or extra joins."
        )
    rejection = None
    for attempt in range(1, 4):
        context = {"contract": contract, "allowed_tools": list(tools)}
        if independent_only:
            context["independent_only"] = True
        if rejection:
            # Only the deterministic validator's error, not previous model text.
            # This requests correction from the model; Python never repairs an
            # invalid DAG, silently drops dependencies, or runs fallback steps.
            context["revision"] = (
                f"Previous plan rejected: {rejection}. Generate a new plan with "
                "all needs referencing defined node ids (or [] for independent "
                "work), exact required fields, and only allowlisted tools."
            )
        try:
            response = _invoke_llm("nina_dag_planner", goal, context)
        except Exception as exc:
            raise WorkflowPlanError(f"planner failed: {type(exc).__name__}") from exc
        if (not response or response.get("invocation_type") != "real_llm"
                or not response.get("response_id") or not response.get("output")):
            raise WorkflowPlanError("real LLM planning and response provenance required")
        try:
            data = json.loads(response["output"], object_pairs_hook=_unique_json_object)
        except (ValueError, TypeError) as exc:
            rejection = ("duplicate JSON member" if "duplicate JSON member" in str(exc)
                         else "planner output is not strict JSON")
            continue
        try:
            nodes = validate_plan(data, allowed_tools=set(tools))
            if independent_only and (not 2 <= len(nodes) <= 4
                                     or any(node.needs or node.tool != "llm_agent"
                                            for node in nodes)):
                raise WorkflowPlanError("independent plan must have 2-4 root LLM nodes")
        except WorkflowPlanError as exc:
            rejection = str(exc)
            continue
        return nodes, {
            "provider": response["provider"], "model": response["model"],
            "response_id": response["response_id"],
            "prompt_digest": response.get("prompt_digest"),
            "attempts": attempt,
        }
    raise WorkflowPlanError(f"planner output invalid after 3 attempts: {rejection}")


def execute_registered_node(node, deps):
    if node.tool == "safe_expression":
        from .agent_runtime import _safe_expression
        return _safe_expression(node.task)
    if node.tool == "local_mcp_tool_registry.sha256":
        from .agent_runtime import _mcp_tool_call
        value = json.dumps(deps, sort_keys=True) if deps else node.task
        return _mcp_tool_call("sha256", {"value": value})
    if node.tool == "vercel_sandbox":
        from .vercel_sandbox_adapter import SandboxAdapterError, execute_sandbox_task
        try:
            return execute_sandbox_task(node.task)
        except SandboxAdapterError as exc:
            raise WorkflowPlanError("Vercel Sandbox task rejected") from exc
    if node.tool == "llm_agent":
        from .agent_runtime import _invoke_llm
        response = _invoke_llm(node.id, node.task, {"upstream_results": deps})
        if (not response or response.get("invocation_type") != "real_llm"
                or not response.get("response_id") or not response.get("output")):
            raise WorkflowPlanError("real subagent execution and response provenance required")
        return {"output": response["output"], "provider": response["provider"],
                "model": response["model"], "response_id": response["response_id"]}
    raise WorkflowPlanError("tool not permitted by workflow executor")


def run_nina_workflow(*, tenant_id, requester_id, goal, allowed_tools, append,
                      planner=model_plan, executor=execute_registered_node,
                      fetch_records=None, require_overlap=False, expected_provider=None):
    from .igor_workflow import verify_dag_records

    # The existing Evidence V4 lifecycle owns the run boundary. Workflow events
    # are nested between these two durable records and share the same run_id.
    supported = {"safe_expression", "local_mcp_tool_registry.sha256", "llm_agent", "vercel_sandbox"}
    if (not isinstance(allowed_tools, (list, tuple)) or not allowed_tools
            or len(allowed_tools) > 16
            or not all(isinstance(tool, str) and tool.strip() for tool in allowed_tools)
            or len(set(allowed_tools)) != len(allowed_tools)):
        raise WorkflowPlanError("invalid workflow tool allowlist")
    if not set(allowed_tools) <= supported:
        raise WorkflowPlanError("unregistered workflow tool")
    allowed_tool_names = sorted(allowed_tools)
    run_id = str(uuid.uuid4())
    source_commit = os.getenv("OLA_RUNTIME_COMMIT") or "UNKNOWN"
    task_digest = _digest(goal)
    start_saved = append(tenant_id, "execution.run.start", {
        "run_id": run_id,
        "task_digest": task_digest,
        "source_commit": source_commit,
        "requester_id": requester_id,
        "commit": source_commit,
        "allowed_tools": allowed_tool_names,
    })
    if not isinstance(start_saved, dict) or not start_saved.get("id"):
        raise RuntimeError("execution start evidence write was not confirmed")
    evidence_ids = [start_saved["id"]]
    workflow_events = []

    try:
        nodes, provenance = planner(goal, tuple(allowed_tool_names))
        nodes = validate_plan({"nodes": [
            {"id": n.id, "tool": n.tool, "task": n.task, "needs": list(n.needs)}
            for n in nodes]}, allowed_tools=set(allowed_tool_names))

        def record(event):
            payload = {**event, "requester_id": requester_id, "planner": provenance,
                       "commit": source_commit, "task_digest": task_digest,
                       "allowed_tools": allowed_tool_names}
            saved = append(tenant_id, event["event"], payload)
            if not isinstance(saved, dict) or not saved.get("id"):
                raise RuntimeError("evidence write was not confirmed")
            evidence_ids.append(saved["id"])
            workflow_events.append(event)

        result = WorkflowEngine(max_workers=4).run(
            nodes, executor, record, run_id=run_id
        )
        preliminary_igor = {"status": "UNKNOWN", "reason": "independent evidence reader not configured"}
        if fetch_records is not None:
            preliminary_igor = verify_dag_records(
                fetch_records(tenant_id), tenant_id=tenant_id, run_id=run_id,
                expected_commit=source_commit if source_commit != "UNKNOWN" else None,
                require_overlap=require_overlap, expected_provider=expected_provider,
                require_lifecycle=False,
            )
    except Exception as exc:
        completed_count = sum(event.get("event") == "task.completed" for event in workflow_events)
        failed_count = sum(event.get("event") == "task.failed" for event in workflow_events)
        try:
            error_saved = append(tenant_id, "execution.run.error", {
                "run_id": run_id,
                "error_type": type(exc).__name__,
                "completed_node_count": completed_count,
                "task_digest": task_digest,
                "source_commit": source_commit,
                "requester_id": requester_id,
                "commit": source_commit,
                "allowed_tools": allowed_tool_names,
            })
            if not isinstance(error_saved, dict) or not error_saved.get("id"):
                raise RuntimeError("execution error evidence write was not confirmed")
            evidence_ids.append(error_saved["id"])
            end_saved = append(tenant_id, "execution.run.end", {
                "run_id": run_id,
                "status": "FAILED",
                "workflow_status": "BLOCK",
                "pre_end_igor_status": "UNKNOWN",
                "task_digest": task_digest,
                "source_commit": source_commit,
                "requester_id": requester_id,
                "commit": source_commit,
                "allowed_tools": allowed_tool_names,
                "completed_node_count": completed_count,
                "failed_node_count": max(1, failed_count),
                "skipped_node_count": 0,
            })
            if not isinstance(end_saved, dict) or not end_saved.get("id"):
                raise RuntimeError("execution end evidence write was not confirmed")
            evidence_ids.append(end_saved["id"])
        except Exception as finalization_error:
            raise RuntimeError("execution lifecycle finalization failed") from finalization_error
        raise

    workflow_status = result["status"]
    completed_count = len(result["results"])
    failed_count = len(result["failed"])
    skipped_count = len(result["skipped"])
    end_saved = append(tenant_id, "execution.run.end", {
        "run_id": run_id,
        "status": "COMPLETED" if workflow_status == "COMPLETED_UNVERIFIED" else "FAILED",
        "workflow_status": workflow_status,
        "pre_end_igor_status": preliminary_igor["status"],
        "task_digest": task_digest,
        "source_commit": source_commit,
        "requester_id": requester_id,
        "commit": source_commit,
        "allowed_tools": allowed_tool_names,
        "completed_node_count": completed_count,
        "failed_node_count": failed_count,
        "skipped_node_count": skipped_count,
    })
    if not isinstance(end_saved, dict) or not end_saved.get("id"):
        raise RuntimeError("execution end evidence write was not confirmed")
    evidence_ids.append(end_saved["id"])

    igor = preliminary_igor
    if fetch_records is not None:
        igor = verify_dag_records(
            fetch_records(tenant_id), tenant_id=tenant_id, run_id=run_id,
            expected_commit=source_commit if source_commit != "UNKNOWN" else None,
            require_overlap=require_overlap, expected_provider=expected_provider,
            require_lifecycle=True,
        )
    if workflow_status != "COMPLETED_UNVERIFIED" or igor["status"] == "BLOCK":
        final_status = "BLOCK"
    elif igor["status"] == "VERIFIED":
        final_status = "COMPLETED_UNVERIFIED"
    else:
        final_status = "UNKNOWN"
    return {**result, "status": final_status, "tenant_id": tenant_id, "planner": provenance,
            "evidence_ids": evidence_ids, "igor": igor, "human_gate": "NOT_APPROVED",
            "verified": False}
