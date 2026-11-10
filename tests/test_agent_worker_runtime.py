import importlib
import importlib.util
import io
import json

import pytest
from pydantic import ValidationError


def _worker_modules():
    protocol_spec = importlib.util.find_spec("app.agent_protocol")
    assert protocol_spec is not None, "versioned worker protocol is not implemented"
    worker_spec = importlib.util.find_spec("app.agent_worker")
    assert worker_spec is not None, "one-shot worker entrypoint is not implemented"
    return importlib.import_module("app.agent_protocol"), importlib.import_module("app.agent_worker")


def _request_data():
    from app.agent_registry import make_agent_instance_spec

    agent = make_agent_instance_spec(
        "hermes-worker-01",
        "Hermes",
        "react",
        capabilities=("tool.safe_expression",),
    )
    return {
        "schema_version": 1,
        "run_id": "00000000-0000-4000-8000-000000000001",
        "agent_id": agent.agent_id,
        "agent_instance_id": "00000000-0000-4000-8000-000000000002",
        "specialist_role": agent.specialist_role,
        "execution_profile": agent.execution_profile,
        "capability": "tool.safe_expression",
        "allowed_capabilities": ["tool.safe_expression"],
        "task": "Calculate 17 times 23.",
        "capability_input": {"expression": "17 * 23"},
        "model_output": {"proposal": "Evaluate the arithmetic expression."},
        "source_commit": "a" * 40,
    }


def test_worker_executes_only_a_registered_safe_capability():
    protocol, worker = _worker_modules()
    request = protocol.AgentWorkerRequest.model_validate_json(json.dumps(_request_data()))

    result = worker.run_agent_worker(request)

    assert result.status == "COMPLETED"
    assert result.capability_result == {"value": 391}
    assert result.agent_id == request.agent_id
    assert result.agent_instance_id == request.agent_instance_id
    assert result.worker_pid > 0
    assert len(result.worker_nonce) == 36
    assert result.model_output_role == "advisory_only"
    assert len(result.input_digest) == 64
    assert len(result.model_output_digest) == 64
    assert len(result.output_digest) == 64


def test_worker_request_rejects_unknown_fields_and_invalid_capability():
    protocol, _ = _worker_modules()
    with pytest.raises(ValidationError):
        protocol.AgentWorkerRequest.model_validate_json(json.dumps({
            **_request_data(),
            "untrusted_shell": "rm -rf /",
        }))

    invalid = _request_data()
    invalid["capability"] = "production.deploy"
    with pytest.raises(ValidationError, match="capability"):
        protocol.AgentWorkerRequest.model_validate_json(json.dumps(invalid))


def test_worker_request_rejects_profile_escalation_and_oversized_payload():
    protocol, _ = _worker_modules()
    invalid_profile = _request_data()
    invalid_profile["execution_profile"] = "multi_agent"
    with pytest.raises(ValidationError, match="execution profile"):
        protocol.AgentWorkerRequest.model_validate_json(json.dumps(invalid_profile))

    oversized = _request_data()
    oversized["capability_input"] = {"blob": "x" * 70000}
    with pytest.raises(ValidationError, match="size"):
        protocol.AgentWorkerRequest.model_validate_json(json.dumps(oversized))


def test_worker_executes_read_only_capability_only_from_supplied_snapshot():
    protocol, worker = _worker_modules()
    request_data = _request_data()
    request_data["capability"] = "tool.read_only"
    request_data["allowed_capabilities"] = ["tool.read_only"]
    request_data["capability_input"] = {"snapshot": {"state": "known"}}
    request = protocol.AgentWorkerRequest.model_validate_json(json.dumps(request_data))

    result = worker.run_agent_worker(request)

    assert result.status == "COMPLETED"
    assert result.capability_result == {"snapshot": {"state": "known"}}


def test_worker_cli_rejects_oversized_stdin_before_json_parsing():
    _, worker = _worker_modules()
    stdout = io.StringIO()
    code = worker.main(
        stdin=io.BytesIO(b"x" * (worker.MAX_REQUEST_BYTES + 1)),
        stdout=stdout,
    )

    assert code == 2
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "request_too_large"
