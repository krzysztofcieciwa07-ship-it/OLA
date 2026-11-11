"""Manifest-backed specialist instance registry."""
from collections.abc import Sequence
from dataclasses import dataclass
import re

from .agent_catalog import (
    EXECUTION_PROFILE_CAPABILITIES,
    load_agent_catalog,
)


@dataclass(frozen=True)
class AgentInstanceSpec:
    agent_id: str
    role: str
    execution_profile: str
    configuration: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not isinstance(self.agent_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]{2,63}", self.agent_id
        ):
            raise ValueError("agent_id must be a stable lowercase identifier")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("specialist role is required")
        if not isinstance(self.execution_profile, str) or not self.execution_profile:
            raise ValueError("execution profile is required")
        if not isinstance(self.configuration, tuple):
            raise TypeError("configuration must be an immutable tuple of key/value pairs")
        keys = []
        for entry in self.configuration:
            if (not isinstance(entry, tuple) or len(entry) != 2
                    or not all(isinstance(part, str) and part for part in entry)):
                raise ValueError("configuration entries must be non-empty string pairs")
            keys.append(entry[0])
        if len(set(keys)) != len(keys):
            raise ValueError("configuration keys must be unique")

    @property
    def specialist_role(self) -> str:
        return self.role


# This is the explicit compatibility manifest for today's legacy six-profile
# entrypoint. It contains one stable instance per specialist; it is not a claim
# that any entry already runs in a distinct process.
DEFAULT_AGENT_MANIFEST = (
    AgentInstanceSpec("hermes-primary", "Hermes", "multi_agent"),
    AgentInstanceSpec("builder-primary", "Builder", "codeact"),
    AgentInstanceSpec("builder-mcp", "Builder", "mcp_tool_use"),
    AgentInstanceSpec("scout-primary", "Scout", "react"),
    AgentInstanceSpec("guardian-primary", "Guardian", "self_reflection"),
    AgentInstanceSpec("archivist-primary", "Archivist", "agentic_rag"),
    AgentInstanceSpec("researcher-primary", "Researcher", "agentic_rag"),
    AgentInstanceSpec("tester-primary", "Tester", "codeact"),
    AgentInstanceSpec("devops-primary", "DevOps", "react"),
    AgentInstanceSpec("sales-primary", "Sales", "react"),
    AgentInstanceSpec("finance-primary", "Finance", "codeact"),
)

DEFAULT_AGENT_ID = "hermes-primary"


def build_agent_registry(
    manifest: Sequence[AgentInstanceSpec],
) -> list[AgentInstanceSpec]:
    """Validate and materialize a manifest without inventing agent identities."""
    if isinstance(manifest, (str, bytes)) or not isinstance(manifest, Sequence):
        raise TypeError("agent registry requires an explicit instance manifest")
    if not manifest:
        raise ValueError("agent manifest must not be empty")

    catalog = load_agent_catalog()
    seen_ids = set()
    registered = []

    for instance in manifest:
        if not isinstance(instance, AgentInstanceSpec):
            raise TypeError("manifest entries must be AgentInstanceSpec values")
        if instance.agent_id in seen_ids:
            raise ValueError(f"duplicate agent_id: {instance.agent_id}")
        seen_ids.add(instance.agent_id)

        definition = catalog.get(instance.role)
        if definition is None:
            raise ValueError(f"unknown specialist role: {instance.role}")
        if instance.execution_profile not in definition.execution_profiles:
            raise ValueError(
                f"profile {instance.execution_profile!r} is not allowed for {instance.role}"
            )
        required_capability = EXECUTION_PROFILE_CAPABILITIES.get(instance.execution_profile)
        if (required_capability is None
                or required_capability not in definition.capability_allowlist):
            raise ValueError(
                f"profile {instance.execution_profile!r} exceeds {instance.role} capability policy"
            )
        registered.append(instance)

    return registered


# Stable, allowlisted identities for the existing six capability stages. These
# bindings choose a specialist instance whose manifest profile matches the
# actual worker profile; no request-time identity generation is performed.
LEGACY_EXECUTION_BINDINGS = {
    "codeact": ("builder-primary", "Builder"),
    "react": ("scout-primary", "Scout"),
    "agentic_rag": ("archivist-primary", "Archivist"),
    "mcp_tool_use": ("builder-mcp", "Builder"),
    "self_reflection": ("guardian-primary", "Guardian"),
    "multi_agent": ("hermes-primary", "Hermes"),
}
