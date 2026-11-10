from typing import Sequence

from .contracts import (
    AgentModelOutput,
    ProviderError,
    ProviderResult,
    digest_json,
)


POLICY_ALLOWED_PROVIDERS = {
    "run_policy": ("ollama", "openai"),
    "code_policy": ("ollama",),
    "allowlisted_sources": ("ollama",),
    "local_read_only": ("ollama",),
    "local_memory_only": ("ollama",),
    "source_provenance_required": ("ollama", "openai"),
    "local_test_only": ("ollama",),
    "infrastructure_allowlist": ("ollama",),
    "approved_sales_sources": ("ollama", "openai"),
    "finance_read_only": ("ollama",),
}


class ProviderGateway:
    """Explicit provider router: policy checks first, no fallback on any provider error."""

    def __init__(self, *, ollama=None, openai=None, policy_map=None):
        self.adapters = {
            "ollama": ollama,
            "openai": openai,
        }
        self.policy_map = policy_map if policy_map is not None else POLICY_ALLOWED_PROVIDERS

    def generate(
        self,
        *,
        provider: str,
        policy: str,
        prompt: str,
        allowed_tools: Sequence[str] = (),
    ) -> ProviderResult:
        allowed = self.policy_map.get(policy)
        if allowed is None:
            raise ProviderError("unknown_provider_policy", "provider policy is not registered")
        if provider not in allowed:
            raise ProviderError("provider_not_allowed_by_policy", "provider is not allowed by this specialist policy")
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise ProviderError("provider_not_configured", "requested provider is not configured")
        if not isinstance(prompt, str) or not prompt or len(prompt.encode("utf-8")) > 32768:
            raise ProviderError("prompt_invalid", "prompt must be non-empty and at most 32 KiB")

        schema = AgentModelOutput.model_json_schema()
        schema_digest = digest_json(schema)
        try:
            response = adapter.generate(prompt=prompt, schema=schema)
            output = AgentModelOutput.model_validate(response["data"])
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("structured_output_invalid", "provider output failed strict schema validation") from exc

        if policy == "source_provenance_required" and not output.evidence_refs:
            raise ProviderError("evidence_refs_required", "source-provenance policy requires evidence references")
        if output.status == "needs_tool":
            if (
                not allowed_tools
                or any(not isinstance(tool, str) or not tool for tool in allowed_tools)
                or len(set(allowed_tools)) != len(allowed_tools)
                or output.tool_name not in set(allowed_tools)
            ):
                raise ProviderError("tool_not_allowlisted", "model requested a tool outside the explicit allowlist")
        elif output.tool_name is not None or output.tool_arguments_json != "":
            raise ProviderError("tool_authority_violation", "model output cannot carry an unapproved tool action")

        return ProviderResult(
            provider=provider,
            model=response["model"],
            model_digest=response["model_digest"],
            request_id=response["request_id"],
            prompt_digest=digest_json({"prompt": prompt}),
            schema_digest=schema_digest,
            raw_response_digest=response["raw_response_digest"],
            output_digest=digest_json(output.model_dump(mode="json")),
            latency_ms=response["latency_ms"],
            output=output,
            fallback_used=False,
            model_output_role="advisory_only",
        )
