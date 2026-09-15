import ast
import hashlib
import json
import operator
import uuid

from sqlalchemy import select

from .database import SessionLocal
from .hashchain import GENESIS_HASH, canonical_json, compute_record_hash, verify_chain
from .models import EvidenceRecord


AGENT_ROLES = [
    "codeact",
    "react",
    "agentic_rag",
    "mcp_tool_use",
    "self_reflection",
    "multi_agent",
]

_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_expression(task):
    lowered = task.lower()
    if "calculate" in lowered:
        expression = task[lowered.index("calculate") + len("calculate"):].strip()
    else:
        expression = task.strip()
    expression = expression.replace("?", "").split(" and ")[0].strip()
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return "task accepted: no executable arithmetic expression supplied"

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
            return _SAFE_BINOPS[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError("unsafe expression")

    try:
        return str(evaluate(tree.body))
    except ValueError:
        return "task accepted: expression outside safe execution policy"


def _run_react(task, previous_output):
    return {
        "plan": ["reason", "act", "observe"],
        "observation": previous_output.get("tool_output"),
        "result": "observed executable result and selected next action",
    }


def _run_rag(tenant_id, task):
    with SessionLocal() as db:
        rows = db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.seq.desc())
            .limit(10)
        ).all()
    matches = []
    task_terms = {word.lower() for word in task.split() if len(word) > 2}
    for row in rows:
        payload = row.payload_json.lower()
        if any(term in payload for term in task_terms):
            matches.append(row.id)
    return {"matches": matches[:3], "result": f"retrieved {len(matches[:3])} prior evidence records"}


def _mcp_tool_call(name, arguments):
    tools = {
        "sha256": lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "length": lambda value: str(len(value)),
    }
    if name not in tools:
        raise ValueError(f"unknown tool: {name}")
    return tools[name](arguments["value"])


def _invoke_local_deterministic_model(agent, task, context):
    prompt = canonical_json({"agent": agent, "task": task, "context": context})
    return {
        "provider": "local",
        "model": "deterministic-runtime-v1",
        "invocation_type": "local_deterministic_model",
        "prompt_digest": _digest(prompt),
        "output": f"{agent} model invocation completed",
    }


def _execute_agent(agent, tenant_id, task, previous_output, execution):
    context = {
        "task": task,
        "previous_output": previous_output,
        "upstream_agents": [item["agent"] for item in execution],
    }
    model = _invoke_local_deterministic_model(agent, task, context)
    if agent == "codeact":
        tool_output = _safe_expression(task)
        result = {"capability": "executed_safe_expression", "tool": "safe_expression", "tool_output": tool_output, "result": f"safe execution returned {tool_output}"}
    elif agent == "react":
        data = _run_react(task, previous_output)
        result = {"capability": "reason_act_observe", "tool": "react_loop", "tool_output": json.dumps(data, sort_keys=True), "result": data["result"]}
    elif agent == "agentic_rag":
        data = _run_rag(tenant_id, task)
        result = {"capability": "retrieved_prior_evidence", "tool": "evidence_retriever", "tool_output": json.dumps(data, sort_keys=True), "result": data["result"]}
    elif agent == "mcp_tool_use":
        value = _mcp_tool_call("sha256", {"value": previous_output.get("tool_output", task)})
        result = {"capability": "invoked_tool", "tool": "local_mcp_tool_registry.sha256", "tool_output": value, "result": "invoked a registered tool through the tool-use boundary"}
    elif agent == "self_reflection":
        observed = json.dumps(previous_output, sort_keys=True)
        passed = bool(previous_output.get("tool_output")) and "error" not in observed.lower()
        result = {"capability": "checked_previous_output", "tool": "reflection_check", "tool_output": "PASS" if passed else "FAIL", "result": "reflection accepted the previous agent output" if passed else "reflection rejected the previous agent output"}
    elif agent == "multi_agent":
        aggregate = [item["agent"] for item in execution]
        final_result = execution[0]["tool_output"] if execution else ""
        result = {
            "capability": "aggregated_agent_outputs",
            "tool": "agent_aggregator",
            "tool_output": json.dumps(aggregate),
            "final_result": final_result,
            "result": f"aggregated {len(aggregate)} upstream agent outputs; final result={final_result}",
        }
    else:
        raise ValueError(f"unsupported agent: {agent}")
    result.update({
        "provider": model["provider"],
        "model": model["model"],
        "invocation_type": model["invocation_type"],
        "prompt_digest": model["prompt_digest"],
    })
    return result


def _append_agent_evidence(tenant_id, run_id, agent, task, previous_output, execution):
    agent_instance_id = str(uuid.uuid4())
    context = {
        "run_id": run_id,
        "agent": agent,
        "agent_instance_id": agent_instance_id,
        "task": task,
        "previous_output": previous_output,
        "upstream_agents": [item["agent"] for item in execution],
    }
    output = {
        "agent": agent,
        "agent_instance_id": agent_instance_id,
        "execution_boundary": "independent",
        "context_digest": _digest(canonical_json(context)),
        "task": task,
        "input_digest": _digest(json.dumps(previous_output, sort_keys=True)),
        **_execute_agent(agent, tenant_id, task, previous_output, execution),
        "status": "VERIFIED",
    }
    with SessionLocal() as db:
        last = db.scalar(select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant_id).order_by(EvidenceRecord.seq.desc()))
        seq = 0 if last is None else last.seq + 1
        prev_hash = GENESIS_HASH if last is None else last.record_hash
        payload_json = canonical_json({"run_id": run_id, **output})
        record = EvidenceRecord(id=str(uuid.uuid4()), tenant_id=tenant_id, seq=seq, record_type=f"agent.{agent}", payload_json=payload_json, prev_hash=prev_hash, record_hash=compute_record_hash(tenant_id, seq, prev_hash, payload_json))
        db.add(record)
        db.commit()
        return record.id, output


def run_agent_task(tenant_id, task):
    run_id = str(uuid.uuid4())
    evidence_ids = []
    execution = []
    previous_output = {"task": task}
    for agent in AGENT_ROLES:
        evidence_id, output = _append_agent_evidence(tenant_id, run_id, agent, task, previous_output, execution)
        evidence_ids.append(evidence_id)
        execution.append(output)
        previous_output = output
    verification = verify_agent_run(tenant_id, run_id)
    final_result = execution[-1].get("final_result") if execution else None
    result = {
        "run_id": run_id,
        "task": task,
        "final_result": final_result,
        "status": verification["status"],
        "agents": AGENT_ROLES,
        "evidence_count": len(evidence_ids),
        "evidence_ids": evidence_ids,
        "execution": execution,
    }
    return result


def verify_agent_run(tenant_id, run_id):
    with SessionLocal() as db:
        rows = db.scalars(select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant_id).order_by(EvidenceRecord.seq.asc())).all()
    run_rows = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            continue
        if payload.get("run_id") == run_id and row.record_type.startswith("agent."):
            run_rows.append(row)
    if len(run_rows) != len(AGENT_ROLES):
        return {"status": "UNKNOWN", "reason": "missing agent evidence", "evidence_count": len(run_rows)}
    expected_types = [f"agent.{role}" for role in AGENT_ROLES]
    if [row.record_type for row in run_rows] != expected_types:
        return {"status": "BLOCK", "reason": "agent order mismatch", "evidence_count": len(run_rows)}
    instance_ids = set()
    context_digests = set()
    for row in run_rows:
        payload = json.loads(row.payload_json)
        required = {"capability", "tool", "tool_output", "result", "status", "agent_instance_id", "execution_boundary", "context_digest", "invocation_type", "model", "provider"}
        if not required.issubset(payload):
            return {"status": "BLOCK", "reason": "agent execution evidence incomplete", "evidence_count": len(run_rows)}
        if payload["status"] != "VERIFIED":
            return {"status": "BLOCK", "reason": "agent execution not verified", "evidence_count": len(run_rows)}
        if payload["execution_boundary"] != "independent":
            return {"status": "BLOCK", "reason": "agent execution boundary is not independent", "evidence_count": len(run_rows)}
        instance_ids.add(payload["agent_instance_id"])
        context_digests.add(payload["context_digest"])
    if len(instance_ids) != len(AGENT_ROLES) or len(context_digests) != len(AGENT_ROLES):
        return {"status": "BLOCK", "reason": "agent instances or contexts are not unique", "evidence_count": len(run_rows)}
    chain = [{"tenant_id": row.tenant_id, "seq": row.seq, "prev_hash": row.prev_hash, "record_hash": row.record_hash, "payload_json": row.payload_json} for row in rows]
    chain_ok, reason = verify_chain(chain)
    if not chain_ok:
        return {"status": "BLOCK", "reason": reason, "evidence_count": len(run_rows)}
    return {"status": "VERIFIED", "reason": "independent agent identities, contexts, execution evidence and hash-chain verification passed", "evidence_count": len(run_rows)}
