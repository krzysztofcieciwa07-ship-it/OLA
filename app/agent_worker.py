"""One-request specialist worker protocol.

A worker is a separate OS process, not a security sandbox. It receives a bounded
JSON request, validates its specialist/profile against the catalogue, performs one
registered capability, emits one bounded JSON response, and exits.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from typing import Any

from .agent_catalog import (
    EXECUTION_PROFILE_CAPABILITIES,
    load_agent_catalog,
)


REQUEST_SCHEMA = "ola.agent-worker.request/v1"
RESPONSE_SCHEMA = "ola.agent-worker.response/v1"
MAX_TASK_CHARS = 4096
MAX_REQUEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 65_536
DEFAULT_TIMEOUT_SECONDS = 30
_SUPPORTED_PROFILES = frozenset(EXECUTION_PROFILE_CAPABILITIES)
_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


class WorkerProtocolError(RuntimeError):
    """A worker failed its bounded request/response contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _validate_identity(agent_id: Any, role: Any, execution_profile: Any):
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError("invalid worker agent_id")
    catalog = load_agent_catalog()
    if not isinstance(role, str) or role not in catalog:
        raise ValueError("unknown specialist role")
    definition = catalog[role]
    if not isinstance(execution_profile, str) or execution_profile not in _SUPPORTED_PROFILES:
        raise ValueError("unknown execution profile")
    if execution_profile not in definition.execution_profiles:
        raise ValueError(f"profile {execution_profile!r} is not allowed for {role}")
    required_capability = EXECUTION_PROFILE_CAPABILITIES[execution_profile]
    if required_capability not in definition.capability_allowlist:
        raise ValueError("execution profile exceeds specialist capability policy")
    if definition.availability_status != "catalogued_legacy_pipeline_only":
        raise ValueError("specialist profile is not available")
    return definition


def _worker_environment() -> dict[str, str]:
    # Deliberately do not inherit OPENAI_API_KEY, database credentials, Stripe
    # credentials, GitHub tokens, cloud credentials, or arbitrary parent env.
    safe_os_keys = (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
        "HOME", "USERPROFILE", "LANG", "LC_ALL", "TZ",
    )
    selected_llm_keys = (
        "OLA_LLM_MODE", "OLA_LLM_TIMEOUT", "OLA_LLM_MODEL",
        "OLLAMA_MODEL", "OLLAMA_BASE_URL", "OLA_OLLAMA_ALLOWED_HOSTS",
        "OLA_OLLAMA_NUM_PREDICT",
    )
    env = {
        key: os.environ[key]
        for key in safe_os_keys + selected_llm_keys
        if key in os.environ
    }
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        # The ZBook profile is Ollama-only. Provider fallback is never inherited.
        "OLA_LLM_PROVIDER": "ollama",
    })
    env.setdefault("OLA_LLM_MODE", "deterministic")
    return env


def _request_payload(*, request_id, agent_id, role, execution_profile, task, context):
    return {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "agent_id": agent_id,
        "specialist_role": role,
        "execution_profile": execution_profile,
        "task": task,
        "context": context,
    }


def run_agent_worker(
    *,
    agent_id: str,
    role: str,
    execution_profile: str,
    task: str,
    context: dict[str, Any],
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Launch exactly one catalogue-approved specialist capability in a child process."""
    definition = _validate_identity(agent_id, role, execution_profile)
    if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
        raise ValueError("worker task exceeds input limit or is empty")
    if not isinstance(context, dict):
        raise ValueError("worker context must be an object")

    try:
        encoded_context = _canonical_json(context).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ValueError("worker context is not valid bounded JSON") from None
    if len(encoded_context) > definition.resource_limits.max_input_bytes:
        raise ValueError("worker context exceeds input limit")

    request_id = str(uuid.uuid4())
    request = _request_payload(
        request_id=request_id,
        agent_id=agent_id,
        role=role,
        execution_profile=execution_profile,
        task=task,
        context=context,
    )
    try:
        request_bytes = _canonical_json(request).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ValueError("worker request is not valid JSON") from None
    input_limit = min(MAX_REQUEST_BYTES, definition.resource_limits.max_input_bytes)
    if len(request_bytes) > input_limit:
        raise ValueError("worker request exceeds input limit")

    configured_timeout = definition.resource_limits.timeout_seconds
    if timeout_seconds is not None:
        if type(timeout_seconds) is not int or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        configured_timeout = min(configured_timeout, timeout_seconds)
    timeout = max(1, min(configured_timeout, DEFAULT_TIMEOUT_SECONDS))

    command = [sys.executable, "-m", "app.agent_worker"]
    project_root = Path(__file__).resolve().parent.parent
    try:
        completed = subprocess.run(
            command,
            input=request_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(project_root),
            env=_worker_environment(),
            timeout=timeout,
            check=False,
            shell=False,
            close_fds=True,
        )
    except subprocess.TimeoutExpired:
        raise WorkerProtocolError("agent worker exceeded its execution timeout") from None
    except OSError:
        raise WorkerProtocolError("agent worker could not be started") from None

    if completed.returncode != 0:
        # Never echo stderr: worker traces can contain paths, prompts or sensitive data.
        raise WorkerProtocolError("agent worker exited without a verified response")
    stdout = completed.stdout or b""
    if not isinstance(stdout, bytes) or len(stdout) > min(
        MAX_RESPONSE_BYTES, definition.resource_limits.max_output_bytes
    ):
        raise WorkerProtocolError("agent worker response exceeds output limit")
    try:
        response = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WorkerProtocolError("agent worker returned invalid JSON") from None

    expected = {
        "schema": RESPONSE_SCHEMA,
        "request_id": request_id,
        "agent_id": agent_id,
        "specialist_role": role,
        "execution_profile": execution_profile,
        "status": "COMPLETED",
    }
    if not isinstance(response, dict) or any(response.get(k) != v for k, v in expected.items()):
        raise WorkerProtocolError("agent worker response identity or status mismatch")
    worker_pid = response.get("worker_pid")
    parent_pid = response.get("worker_parent_pid")
    if (
        type(worker_pid) is not int or worker_pid <= 0
        or type(parent_pid) is not int or parent_pid != os.getpid()
        or worker_pid == os.getpid()
    ):
        raise WorkerProtocolError("agent worker process boundary could not be established")
    result = response.get("result")
    if not isinstance(result, dict):
        raise WorkerProtocolError("agent worker result schema is invalid")
    if response.get("execution_boundary") != "subprocess":
        raise WorkerProtocolError("agent worker did not report a subprocess boundary")

    return {
        "status": "COMPLETED",
        "request_id": request_id,
        "agent_id": agent_id,
        "specialist_role": role,
        "execution_profile": execution_profile,
        "execution_boundary": "subprocess",
        "worker_pid": worker_pid,
        "worker_parent_pid": parent_pid,
        "resource_enforcement": response.get("resource_enforcement"),
        "result": result,
    }


def _apply_worker_resource_limits(definition) -> str:
    """Apply POSIX rlimits before importing the runtime; Windows uses timeout/payload caps."""
    if os.name != "posix":
        return "timeout_and_payload_limits_only"
    try:
        import resource

        limits = definition.resource_limits
        cpu_seconds = max(1, limits.timeout_seconds - 1)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        max_memory = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (max_memory, max_memory))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        return "posix_rlimit_cpu_as_nofile"
    except (ImportError, AttributeError, OSError, ValueError):
        return "timeout_and_payload_limits_only"


def _execute_worker_request(request: Any) -> dict[str, Any]:
    required_keys = {
        "schema", "request_id", "agent_id", "specialist_role",
        "execution_profile", "task", "context",
    }
    if not isinstance(request, dict) or set(request) != required_keys:
        raise ValueError("worker request shape is invalid")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("worker request schema is unsupported")
    try:
        uuid.UUID(request.get("request_id", ""))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("worker request id is invalid") from None

    agent_id = request["agent_id"]
    role = request["specialist_role"]
    profile = request["execution_profile"]
    task = request["task"]
    context = request["context"]
    definition = _validate_identity(agent_id, role, profile)
    if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
        raise ValueError("worker task is invalid")
    if not isinstance(context, dict):
        raise ValueError("worker context is invalid")

    resource_status = _apply_worker_resource_limits(definition)

    # Imported only after applying limits. The child receives no database
    # credentials and capability inputs needed from memory are passed by value.
    from .agent_runtime import (
        _digest,
        _invoke_llm,
        _invoke_local_deterministic_model,
        _mcp_tool_call,
        _run_react,
        _safe_expression,
    )

    model = _invoke_llm(profile, task, context)
    if model is None:
        model = _invoke_local_deterministic_model(profile, task, context)

    previous_output = context.get("previous_output", {})
    if not isinstance(previous_output, dict):
        raise ValueError("previous_output must be an object")

    if profile == "codeact":
        tool_output = _safe_expression(task)
        result = {
            "capability": "executed_safe_expression",
            "tool": "safe_expression",
            "tool_output": tool_output,
            "result": f"safe execution returned {tool_output}",
        }
    elif profile == "react":
        data = _run_react(task, previous_output)
        result = {
            "capability": "reason_act_observe",
            "tool": "react_loop",
            "tool_output": json.dumps(data, sort_keys=True),
            "result": data["result"],
        }
    elif profile == "agentic_rag":
        data = context.get("retrieved_evidence")
        if not isinstance(data, dict):
            raise ValueError("agentic_rag requires parent-resolved evidence context")
        result = {
            "capability": "retrieved_prior_evidence",
            "tool": "evidence_retriever",
            "tool_output": json.dumps(data, sort_keys=True),
            "result": data.get("result", "retrieved evidence context"),
        }
    elif profile == "mcp_tool_use":
        value = _mcp_tool_call(
            "sha256", {"value": previous_output.get("tool_output", task)}
        )
        result = {
            "capability": "invoked_tool",
            "tool": "local_mcp_tool_registry.sha256",
            "tool_output": value,
            "result": "invoked a registered tool through the worker boundary",
        }
    elif profile == "self_reflection":
        observed = json.dumps(previous_output, sort_keys=True)
        passed = bool(previous_output.get("tool_output")) and "error" not in observed.lower()
        result = {
            "capability": "checked_previous_output",
            "tool": "reflection_check",
            "tool_output": "PASS" if passed else "FAIL",
            "result": (
                "reflection accepted the previous agent output"
                if passed else "reflection rejected the previous agent output"
            ),
        }
    elif profile == "multi_agent":
        upstream_execution = context.get("upstream_execution", [])
        upstream_agents = context.get("upstream_agents", [])
        if not isinstance(upstream_execution, list) or not isinstance(upstream_agents, list):
            raise ValueError("multi_agent requires explicit upstream execution context")
        final_result = (
            upstream_execution[0].get("tool_output", "")
            if upstream_execution and isinstance(upstream_execution[0], dict) else ""
        )
        result = {
            "capability": "aggregated_agent_outputs",
            "tool": "agent_aggregator",
            "tool_output": json.dumps(upstream_agents),
            "final_result": final_result,
            "result": (
                f"aggregated {len(upstream_agents)} upstream agent outputs; "
                f"final result={final_result}"
            ),
        }
    else:  # defensive: catalogue is the authority
        raise ValueError("unsupported specialist execution profile")

    result.update({
        "provider": model["provider"],
        "model": model["model"],
        "invocation_type": model["invocation_type"],
        "prompt_digest": model["prompt_digest"],
        "response_id": model.get("response_id"),
        "model_output_digest": _digest(model.get("output", "")),
        "model_output_role": "advisory_only",
        "action_result_source": "registered_capability",
    })
    return {
        "schema": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "agent_id": agent_id,
        "specialist_role": role,
        "execution_profile": profile,
        "status": "COMPLETED",
        "execution_boundary": "subprocess",
        "worker_pid": os.getpid(),
        "worker_parent_pid": os.getppid(),
        "resource_enforcement": resource_status,
        "result": result,
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            return 2
        request = json.loads(raw.decode("utf-8"))
        response = _execute_worker_request(request)
        output = _canonical_json(response).encode("utf-8")
        if len(output) > MAX_RESPONSE_BYTES:
            return 3
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        return 0
    except Exception as exc:
        # Send no exception message or traceback across the process boundary.
        try:
            sys.stderr.write(type(exc).__name__ + "\n")
        except Exception:
            pass
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
