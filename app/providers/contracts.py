import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AgentModelOutput(BaseModel):
    """Strict, advisory-only JSON contract shared by local and hosted providers."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: Literal["complete", "needs_tool", "blocked"]
    summary: str = Field(min_length=1, max_length=2000)
    reasoning: str = Field(min_length=1, max_length=4000)
    tool_name: str | None
    tool_arguments: dict[str, Any]
    evidence_refs: list[str] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_authority_and_bounds(self):
        if self.status == "needs_tool":
            if not isinstance(self.tool_name, str) or not self.tool_name:
                raise ValueError("needs_tool requires a tool_name")
        elif self.tool_name is not None or self.tool_arguments:
            raise ValueError("tool calls are only valid when status is needs_tool")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs must be unique")
        if any(not ref or len(ref) > 256 for ref in self.evidence_refs):
            raise ValueError("evidence_refs must be non-empty bounded strings")
        if len(canonical_json(self.tool_arguments).encode("utf-8")) > 16384:
            raise ValueError("tool_arguments exceed the output contract limit")
        return self


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: Literal["ollama", "openai"]
    model: str = Field(min_length=1, max_length=128)
    model_digest: str | None
    request_id: str = Field(min_length=1, max_length=256)
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_response_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    latency_ms: int = Field(ge=0)
    output: AgentModelOutput
    fallback_used: Literal[False] = False
    model_output_role: Literal["advisory_only"] = "advisory_only"

    @model_validator(mode="after")
    def validate_model_digest(self):
        if self.provider == "ollama":
            if not isinstance(self.model_digest, str) or not self.model_digest.startswith("sha256:"):
                raise ValueError("Ollama provenance requires a content digest")
        elif self.model_digest is not None:
            raise ValueError("OpenAI model digest is provider-managed and must be null")
        if self.output_digest != digest_json(self.output.model_dump(mode="json")):
            raise ValueError("output digest does not match structured output")
        return self
