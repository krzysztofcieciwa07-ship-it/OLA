import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_catalog import load_agent_catalog


MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 65536
MAX_PAYLOAD_BYTES = 32768

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


from .canonical import canonical_json, digest_json
def _json_size(value: Any) -> int:
    try:
        return len(canonical_json(value).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("payload must be finite JSON data") from exc


def _validate_uuid(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _UUID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical UUIDv4")
    if str(uuid.UUID(value)) != value:
        raise ValueError(f"{field_name} must be a canonical UUIDv4")
    return value


class AgentWorkerRequest(BaseModel):
    """One-shot, versioned, strictly validated worker input."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    run_id: str = Field(min_length=36, max_length=36)
    agent_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    agent_instance_id: str = Field(min_length=36, max_length=36)
    specialist_role: str = Field(min_length=1, max_length=64)
    execution_profile: str = Field(min_length=1, max_length=32)
    capability: str = Field(min_length=1, max_length=96)
    allowed_capabilities: tuple[str, ...] = Field(min_length=1, max_length=32)
    task: str = Field(min_length=1, max_length=4096)
    capability_input: dict[str, Any]
    model_output: dict[str, Any]
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")

    @model_validator(mode="after")
    def validate_scope_and_bounds(self):
        _validate_uuid(self.run_id, "run_id")
        _validate_uuid(self.agent_instance_id, "agent_instance_id")

        if len(set(self.allowed_capabilities)) != len(self.allowed_capabilities):
            raise ValueError("allowed_capabilities must be unique")

        catalog = load_agent_catalog()
        definition = catalog.get(self.specialist_role)
        if definition is None or definition.kind != "specialist":
            raise ValueError("unknown or non-worker specialist role")
        if self.execution_profile not in definition.execution_profiles:
            raise ValueError("unsupported execution profile for specialist")
        if not set(self.allowed_capabilities).issubset(definition.capabilities):
            raise ValueError("capability allowlist exceeds specialist policy")
        if self.capability not in self.allowed_capabilities:
            raise ValueError("requested capability is not in the worker allowlist")
        if _json_size(self.capability_input) > MAX_PAYLOAD_BYTES:
            raise ValueError("capability input size exceeds the worker limit")
        if _json_size(self.model_output) > MAX_PAYLOAD_BYTES:
            raise ValueError("model output size exceeds the worker limit")
        model_output = self.model_output.get("output")
        if not isinstance(model_output, dict):
            raise ValueError("worker request must contain parsed structured model output")
        if model_output.get("status") != "needs_tool":
            raise ValueError("model output must explicitly request a capability")
        if model_output.get("tool_name") != self.capability:
            raise ValueError("model output capability does not match the requested capability")
        arguments_json = model_output.get("tool_arguments_json")
        if not isinstance(arguments_json, str) or len(arguments_json.encode("utf-8")) > 16384:
            raise ValueError("model output tool arguments are missing or too large")
        try:
            model_arguments = json.loads(arguments_json)
        except json.JSONDecodeError:
            raise ValueError("model output tool arguments are invalid JSON") from None
        if not isinstance(model_arguments, dict) or model_arguments != self.capability_input:
            raise ValueError("capability input is not derived from model output")
        return self


class AgentWorkerResult(BaseModel):
    """Worker output; the supervisor supplies the trusted container identity."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    status: Literal["COMPLETED", "BLOCKED"]
    run_id: str = Field(min_length=36, max_length=36)
    agent_id: str = Field(min_length=1, max_length=64)
    agent_instance_id: str = Field(min_length=36, max_length=36)
    specialist_role: str
    execution_profile: str
    capability: str
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    worker_pid: int = Field(gt=0)
    worker_nonce: str = Field(min_length=36, max_length=36)
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_output_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    worker_public_key: str = Field(min_length=44, max_length=44)
    worker_signature: str = Field(min_length=88, max_length=88)
    attestation_version: Literal[1] = 1
    model_output_role: Literal["advisory_only"] = "advisory_only"
    capability_result: dict[str, Any]
    reason: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self):
        _validate_uuid(self.run_id, "run_id")
        _validate_uuid(self.agent_instance_id, "agent_instance_id")
        _validate_uuid(self.worker_nonce, "worker_nonce")
        if _json_size(self.capability_result) > MAX_PAYLOAD_BYTES:
            raise ValueError("capability result size exceeds the worker limit")
        return self
