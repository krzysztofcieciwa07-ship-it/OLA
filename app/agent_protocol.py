"""Versioned strict JSON contracts for one-shot OLA specialist workers.

This module intentionally has no database, HTTP, Docker, or LLM dependencies so
it can be copied into a minimal worker image.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import uuid
from typing import Any


REQUEST_SCHEMA = "ola.agent-worker.request/v1"
RESULT_SCHEMA = "ola.agent-worker.result/v1"
MAX_REQUEST_BYTES = 16_384
MAX_RESULT_BYTES = 65_536
MAX_TASK_CHARS = 4096
_MAX_MODEL_OUTPUT_CHARS = 8192
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")
_AGENT_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


class AgentProtocolError(ValueError):
    """A worker protocol message did not satisfy its strict schema."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _uuid4(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise AgentProtocolError(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise AgentProtocolError(f"{field} must be a UUID string") from None
    if parsed.version != 4 or str(parsed) != value:
        raise AgentProtocolError(f"{field} must be a canonical UUIDv4")
    return value


def _exact_keys(value: Any, required: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise AgentProtocolError(f"{field} has missing or unknown fields")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX_256.fullmatch(value):
        raise AgentProtocolError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class AgentWorkerRequest:
    request_id: str
    run_id: str
    agent_id: str
    agent_instance_id: str
    specialist_role: str
    profile: str
    task: str
    context: dict[str, Any]
    capability_name: str
    model_provider: str
    model_name: str
    invocation_type: str
    model_response_id: str | None
    prompt_digest: str
    model_output_digest: str
    model_output: str

    @classmethod
    def from_json(cls, raw: bytes) -> "AgentWorkerRequest":
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_REQUEST_BYTES:
            raise AgentProtocolError("worker request is empty or exceeds byte limit")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AgentProtocolError("worker request is not valid UTF-8 JSON") from None
        fields = {
            "schema", "request_id", "run_id", "agent_id", "agent_instance_id",
            "specialist_role", "profile", "task", "context", "capability",
            "model_response",
        }
        _exact_keys(body, fields, "worker request")
        if body["schema"] != REQUEST_SCHEMA:
            raise AgentProtocolError("unsupported worker request schema")
        request_id = _uuid4(body["request_id"], "request_id")
        run_id = _uuid4(body["run_id"], "run_id")
        instance_id = _uuid4(body["agent_instance_id"], "agent_instance_id")
        if not isinstance(body["agent_id"], str) or not _AGENT_ID.fullmatch(body["agent_id"]):
            raise AgentProtocolError("agent_id is invalid")
        if not isinstance(body["specialist_role"], str) or not body["specialist_role"]:
            raise AgentProtocolError("specialist_role is required")
        if not isinstance(body["profile"], str) or not body["profile"]:
            raise AgentProtocolError("profile is required")
        if (not isinstance(body["task"], str) or not body["task"].strip()
                or len(body["task"]) > MAX_TASK_CHARS):
            raise AgentProtocolError("task is empty or exceeds character limit")
        if not isinstance(body["context"], dict):
            raise AgentProtocolError("context must be an object")
        if len(canonical_json(body["context"]).encode("utf-8")) > 8192:
            raise AgentProtocolError("context exceeds byte limit")

        capability = _exact_keys(body["capability"], {"name", "allowed"}, "capability")
        if capability["allowed"] is not True or not isinstance(capability["name"], str):
            raise AgentProtocolError("capability is not explicitly allowed")

        model = _exact_keys(
            body["model_response"],
            {"provider", "model", "invocation_type", "response_id",
             "prompt_digest", "output_digest", "output"},
            "model_response",
        )
        if model["provider"] not in {"ollama", "openai", "local"}:
            raise AgentProtocolError("unsupported model provider")
        if not isinstance(model["model"], str) or not model["model"]:
            raise AgentProtocolError("model name is required")
        if model["invocation_type"] not in {"real_llm", "local_deterministic_model"}:
            raise AgentProtocolError("unsupported invocation type")
        if model["invocation_type"] == "real_llm":
            if not isinstance(model["response_id"], str) or not model["response_id"]:
                raise AgentProtocolError("real model response identity is required")
        elif model["response_id"] is not None:
            raise AgentProtocolError("deterministic response must not claim a provider response id")
        if not isinstance(model["output"], str) or len(model["output"]) > _MAX_MODEL_OUTPUT_CHARS:
            raise AgentProtocolError("model output is invalid or too large")
        _digest(model["prompt_digest"], "prompt_digest")
        _digest(model["output_digest"], "model output digest")

        return cls(
            request_id=request_id,
            run_id=run_id,
            agent_id=body["agent_id"],
            agent_instance_id=instance_id,
            specialist_role=body["specialist_role"],
            profile=body["profile"],
            task=body["task"],
            context=body["context"],
            capability_name=capability["name"],
            model_provider=model["provider"],
            model_name=model["model"],
            invocation_type=model["invocation_type"],
            model_response_id=model["response_id"],
            prompt_digest=model["prompt_digest"],
            model_output_digest=model["output_digest"],
            model_output=model["output"],
        )


@dataclass(frozen=True)
class AgentWorkerResult:
    request_id: str
    run_id: str
    agent_id: str
    agent_instance_id: str
    specialist_role: str
    profile: str
    status: str
    worker_pid: int
    result: dict[str, Any]
    result_digest: str

    def to_json(self) -> bytes:
        payload = {
            "schema": RESULT_SCHEMA,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "agent_instance_id": self.agent_instance_id,
            "specialist_role": self.specialist_role,
            "profile": self.profile,
            "status": self.status,
            "worker_pid": self.worker_pid,
            "result": self.result,
            "result_digest": self.result_digest,
        }
        raw = canonical_json(payload).encode("utf-8")
        if len(raw) > MAX_RESULT_BYTES:
            raise AgentProtocolError("worker result exceeds byte limit")
        return raw

    @classmethod
    def from_json(cls, raw: bytes) -> "AgentWorkerResult":
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RESULT_BYTES:
            raise AgentProtocolError("worker result is empty or exceeds byte limit")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AgentProtocolError("worker result is not valid UTF-8 JSON") from None
        fields = {
            "schema", "request_id", "run_id", "agent_id", "agent_instance_id",
            "specialist_role", "profile", "status", "worker_pid", "result",
            "result_digest",
        }
        _exact_keys(body, fields, "worker result")
        if body["schema"] != RESULT_SCHEMA:
            raise AgentProtocolError("unsupported worker result schema")
        _uuid4(body["request_id"], "request_id")
        _uuid4(body["run_id"], "run_id")
        _uuid4(body["agent_instance_id"], "agent_instance_id")
        if body["status"] != "COMPLETED":
            raise AgentProtocolError("worker did not complete successfully")
        if type(body["worker_pid"]) is not int or body["worker_pid"] != 1:
            raise AgentProtocolError("worker must run as container PID 1")
        if not isinstance(body["result"], dict):
            raise AgentProtocolError("worker result payload must be an object")
        _digest(body["result_digest"], "result_digest")
        if sha256_json(body["result"]) != body["result_digest"]:
            raise AgentProtocolError("worker result digest mismatch")
        return cls(
            request_id=body["request_id"],
            run_id=body["run_id"],
            agent_id=body["agent_id"],
            agent_instance_id=body["agent_instance_id"],
            specialist_role=body["specialist_role"],
            profile=body["profile"],
            status=body["status"],
            worker_pid=body["worker_pid"],
            result=body["result"],
            result_digest=body["result_digest"],
        )
