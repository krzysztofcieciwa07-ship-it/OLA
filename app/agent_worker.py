import ast
import io
import json
import math
import operator
import os
import sys
import uuid
from typing import Any, BinaryIO, TextIO

from pydantic import ValidationError

from .provenance.crypto import sign_worker_payload, worker_attestation_payload
from .agent_protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    AgentWorkerRequest,
    AgentWorkerResult,
    digest_json,
)


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _bounded_number(value: Any) -> int | float:
    if type(value) not in (int, float):
        raise ValueError("expression result must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite arithmetic result")
    if abs(value) > 1_000_000_000_000:
        raise ValueError("arithmetic result exceeds the configured bound")
    return value


def _evaluate_expression(node: ast.AST, depth: int = 0) -> int | float:
    if depth > 16:
        raise ValueError("expression depth limit exceeded")
    if isinstance(node, ast.Expression):
        return _evaluate_expression(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        return _bounded_number(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        value = _evaluate_expression(node.operand, depth + 1)
        return _bounded_number(_UNARY_OPERATORS[type(node.op)](value))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_expression(node.left, depth + 1)
        right = _evaluate_expression(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("exponent exceeds the configured bound")
        return _bounded_number(_BINARY_OPERATORS[type(node.op)](left, right))
    raise ValueError("expression contains a forbidden operation")


def _safe_expression(expression: Any) -> int | float:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 256:
        raise ValueError("expression must be a short non-empty string")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("expression syntax is invalid") from exc
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("expression complexity limit exceeded")
    return _evaluate_expression(tree)


def _capability_safe_expression(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"expression"}:
        raise ValueError("safe_expression accepts only an expression")
    return {"value": _safe_expression(payload["expression"])}


def _capability_read_only(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"snapshot"} or not isinstance(payload["snapshot"], dict):
        raise ValueError("read_only accepts one object snapshot")
    # The worker only returns supervisor-supplied data; it cannot read the host.
    return {"snapshot": payload["snapshot"]}


_CAPABILITY_HANDLERS = {
    "tool.safe_expression": _capability_safe_expression,
    "tool.read_only": _capability_read_only,
}


def _result(request: AgentWorkerRequest, status: str, capability_result: dict[str, Any],
            reason: str | None = None) -> AgentWorkerResult:
    worker_pid = os.getpid()
    worker_nonce = str(uuid.uuid4())
    input_payload = {"task": request.task, "capability_input": request.capability_input}
    request_digest = digest_json(request.model_dump(mode="json"))
    input_digest = digest_json(input_payload)
    capability_input_digest = digest_json(request.capability_input)
    model_output_digest = digest_json(request.model_output)
    attestation_payload = worker_attestation_payload(
        schema_version=1,
        run_id=request.run_id,
        agent_id=request.agent_id,
        agent_instance_id=request.agent_instance_id,
        specialist_role=request.specialist_role,
        execution_profile=request.execution_profile,
        capability=request.capability,
        source_commit=request.source_commit,
        worker_pid=worker_pid,
        worker_nonce=worker_nonce,
        request_digest=request_digest,
        input_digest=input_digest,
        capability_input_digest=capability_input_digest,
        model_output_digest=model_output_digest,
        capability_result=capability_result,
    )
    worker_public_key, worker_signature = sign_worker_payload(attestation_payload)
    return AgentWorkerResult(
        schema_version=1,
        status=status,
        run_id=request.run_id,
        agent_id=request.agent_id,
        agent_instance_id=request.agent_instance_id,
        specialist_role=request.specialist_role,
        execution_profile=request.execution_profile,
        capability=request.capability,
        source_commit=request.source_commit,
        worker_pid=worker_pid,
        worker_nonce=worker_nonce,
        request_digest=request_digest,
        input_digest=input_digest,
        capability_input_digest=capability_input_digest,
        model_output_digest=model_output_digest,
        output_digest=digest_json(attestation_payload),
        worker_public_key=worker_public_key,
        worker_signature=worker_signature,
        attestation_version=1,
        model_output_role="advisory_only",
        capability_result=capability_result,
        reason=reason,
    )


def run_agent_worker(request: AgentWorkerRequest) -> AgentWorkerResult:
    """Execute one registered, pure capability inside a one-shot worker process."""
    if not isinstance(request, AgentWorkerRequest):
        raise TypeError("request must be a validated AgentWorkerRequest")
    handler = _CAPABILITY_HANDLERS.get(request.capability)
    if handler is None:
        return _result(request, "BLOCKED", {}, "capability_not_implemented")
    try:
        capability_result = handler(request.capability_input)
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return _result(request, "BLOCKED", {}, "capability_input_invalid")
    return _result(request, "COMPLETED", capability_result)


def _write_error(stdout: TextIO, reason: str) -> None:
    stdout.write(json.dumps({"status": "BLOCKED", "reason": reason}, separators=(",", ":")) + "\n")


def main(stdin: BinaryIO | None = None, stdout: TextIO | None = None) -> int:
    """Read exactly one bounded JSON request and write exactly one JSON response."""
    source = stdin if stdin is not None else sys.stdin.buffer
    sink = stdout if stdout is not None else sys.stdout
    try:
        raw = source.read(MAX_REQUEST_BYTES + 1)
    except Exception:
        _write_error(sink, "request_read_failed")
        return 2
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        _write_error(sink, "request_too_large" if raw else "request_empty")
        return 2
    try:
        request = AgentWorkerRequest.model_validate_json(raw)
    except (ValidationError, ValueError, TypeError):
        _write_error(sink, "invalid_request")
        return 2

    try:
        result = run_agent_worker(request)
        serialized = result.model_dump_json()
        if len(serialized.encode("utf-8")) > MAX_RESPONSE_BYTES:
            _write_error(sink, "response_too_large")
            return 2
        sink.write(serialized + "\n")
        return 0 if result.status == "COMPLETED" else 2
    except Exception:
        _write_error(sink, "worker_execution_failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
