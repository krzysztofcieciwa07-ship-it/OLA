"""Minimal one-shot entrypoint for isolated OLA specialist containers.

No database, network client, LLM provider, Docker CLI, or evidence writer is
imported here. Model output and a capability envelope arrive as validated JSON.
"""
from __future__ import annotations

import os
import sys

from .agent_catalog import load_agent_catalog
from .agent_capabilities import execute_registered_capability, result_digest
from .agent_protocol import (
    AgentProtocolError,
    AgentWorkerRequest,
    AgentWorkerResult,
    MAX_REQUEST_BYTES,
)


def execute_worker_request(request: AgentWorkerRequest) -> AgentWorkerResult:
    catalog = load_agent_catalog()
    definition = catalog.get(request.specialist_role)
    if definition is None:
        raise AgentProtocolError("unknown specialist role")
    if request.profile not in definition.execution_profiles:
        raise AgentProtocolError("profile is not authorized for specialist")
    if definition.availability_status != "worker_container_v1":
        raise AgentProtocolError("specialist is not enabled for container execution")
    if request.runtime_profile == "test" and request.model_provider == "local":
        if request.invocation_type != "local_deterministic_model":
            raise AgentProtocolError("test runtime local provider metadata is inconsistent")
    elif request.model_provider not in definition.provider_policy.allowed_providers:
        raise AgentProtocolError("provider is not authorized for specialist")
    if request.runtime_profile == "zbook":
        if request.model_provider != "ollama":
            raise AgentProtocolError("ZBook worker requires Ollama")
        if request.invocation_type != "real_llm":
            raise AgentProtocolError("ZBook worker rejects deterministic model responses")
        if not request.model_response_id:
            raise AgentProtocolError("ZBook worker requires a real Ollama response identity")
    result = execute_registered_capability(request)
    return AgentWorkerResult(
        request_id=request.request_id,
        run_id=request.run_id,
        agent_id=request.agent_id,
        agent_instance_id=request.agent_instance_id,
        specialist_role=request.specialist_role,
        profile=request.profile,
        status="COMPLETED",
        worker_pid=os.getpid(),
        result=result,
        result_digest=result_digest(result),
    )


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        request = AgentWorkerRequest.from_json(raw)
        result = execute_worker_request(request)
        sys.stdout.buffer.write(result.to_json())
        sys.stdout.buffer.flush()
        return 0
    except Exception as exc:
        # No exception detail, traceback, path, task or model output crosses the
        # container boundary on stderr.
        try:
            sys.stderr.write(type(exc).__name__ + "\n")
            sys.stderr.flush()
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
