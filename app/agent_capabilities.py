"""Pure, database-free registered capabilities used only inside worker containers."""
from __future__ import annotations

import ast
import hashlib
import json
import operator
from typing import Any

from .agent_catalog import EXECUTION_PROFILE_CAPABILITIES
from .agent_protocol import AgentProtocolError, AgentWorkerRequest, sha256_json


_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
MAX_EXPRESSION_NODES = 128
MAX_EXPRESSION_DEPTH = 24
MAX_LITERAL_ABS = 10**12


def _safe_expression(task: str) -> str:
    lowered = task.lower()
    if "calculate" in lowered:
        expression = task[lowered.index("calculate") + len("calculate"):].strip()
    else:
        expression = task.strip()
    expression = expression.replace("?", "").split(" and ")[0].strip()
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, MemoryError):
        return "task accepted: no executable arithmetic expression supplied"
    if len(list(ast.walk(tree))) > MAX_EXPRESSION_NODES:
        return "execution blocked: expression exceeds safe complexity limit"

    def evaluate(node, depth=0):
        if depth > MAX_EXPRESSION_DEPTH:
            raise ValueError("expression nesting limit exceeded")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if abs(node.value) > MAX_LITERAL_ABS:
                raise ValueError("numeric literal exceeds safe range")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
            return _SAFE_BINOPS[type(node.op)](
                evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            )
        raise ValueError("unsafe expression")

    try:
        value = evaluate(tree.body)
        if isinstance(value, (int, float)) and abs(value) > MAX_LITERAL_ABS:
            return "task accepted: result exceeds safe numeric range"
        return str(value)
    except (ValueError, ArithmeticError, RecursionError, OverflowError):
        return "task accepted: expression outside safe execution policy"


def _execute_react(task: str, previous_output: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": ["reason", "act", "observe"],
        "observation": previous_output.get("tool_output"),
        "result": "observed executable result and selected next action",
    }


def _execute_rag(context: dict[str, Any]) -> dict[str, Any]:
    evidence = context.get("retrieved_evidence")
    if not isinstance(evidence, dict):
        raise AgentProtocolError("agentic_rag requires supervisor-supplied evidence context")
    return evidence


def execute_registered_capability(request: AgentWorkerRequest) -> dict[str, Any]:
    expected = EXECUTION_PROFILE_CAPABILITIES.get(request.profile)
    if expected is None or request.capability_name != expected:
        raise AgentProtocolError("capability does not match registered execution profile")
    previous = request.context.get("previous_output", {})
    if not isinstance(previous, dict):
        raise AgentProtocolError("previous_output must be an object")

    if request.profile == "codeact":
        tool_output = _safe_expression(request.task)
        result = {
            "capability": "executed_safe_expression",
            "tool": "safe_expression",
            "tool_output": tool_output,
            "result": f"safe execution returned {tool_output}",
        }
    elif request.profile == "react":
        observation = _execute_react(request.task, previous)
        result = {
            "capability": "reason_act_observe",
            "tool": "react_loop",
            "tool_output": json.dumps(observation, sort_keys=True),
            "result": observation["result"],
        }
    elif request.profile == "agentic_rag":
        evidence = _execute_rag(request.context)
        result = {
            "capability": "retrieved_prior_evidence",
            "tool": "evidence_retriever",
            "tool_output": json.dumps(evidence, sort_keys=True),
            "result": evidence.get("result", "retrieved evidence context"),
        }
    elif request.profile == "mcp_tool_use":
        value = previous.get("tool_output", request.task)
        result = {
            "capability": "invoked_tool",
            "tool": "local_mcp_tool_registry.sha256",
            "tool_output": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "result": "invoked a registered local hash capability",
        }
    elif request.profile == "self_reflection":
        observed = json.dumps(previous, sort_keys=True)
        passed = bool(previous.get("tool_output")) and "error" not in observed.lower()
        result = {
            "capability": "checked_previous_output",
            "tool": "reflection_check",
            "tool_output": "PASS" if passed else "FAIL",
            "result": "reflection accepted previous output" if passed else "reflection rejected previous output",
        }
    elif request.profile == "multi_agent":
        upstream = request.context.get("upstream_execution", [])
        upstream_agents = request.context.get("upstream_agents", [])
        if not isinstance(upstream, list) or not isinstance(upstream_agents, list):
            raise AgentProtocolError("multi_agent requires bounded upstream execution data")
        first_output = upstream[0].get("tool_output", "") if upstream and isinstance(upstream[0], dict) else ""
        result = {
            "capability": "aggregated_agent_outputs",
            "tool": "agent_aggregator",
            "tool_output": json.dumps(upstream_agents),
            "final_result": first_output,
            "result": f"aggregated {len(upstream_agents)} upstream outputs; final result={first_output}",
        }
    else:
        raise AgentProtocolError("unsupported execution profile")

    result.update({
        "provider": request.model_provider,
        "model": request.model_name,
        "invocation_type": request.invocation_type,
        "response_id": request.model_response_id,
        "prompt_digest": request.prompt_digest,
        "model_output_digest": request.model_output_digest,
        "model_output_role": "advisory_only",
        "action_result_source": "registered_capability",
    })
    return result


def result_digest(result: dict[str, Any]) -> str:
    return sha256_json(result)
