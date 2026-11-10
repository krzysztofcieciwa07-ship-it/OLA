import re
from collections.abc import Sequence
from dataclasses import dataclass

from .agent_catalog import AgentDefinition, ResourceLimits, load_agent_catalog


_AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ALLOWED_STATUSES = frozenset({"enabled", "disabled"})


@dataclass(frozen=True, slots=True)
class AgentInstanceSpec:
    agent_id: str
    specialist_role: str
    execution_profile: str
    capabilities: tuple[str, ...]
    memory_namespace: str
    provider_policy: str
    resource_limits: ResourceLimits
    approval_policy: str
    availability_status: str = "enabled"

    @property
    def role(self) -> str:
        """Compatibility alias for the historical simulation interface."""
        return self.specialist_role


# Compatibility name for older callers; this is a typed instance, not a role label.
Agent = AgentInstanceSpec


def make_agent_instance_spec(
    agent_id: str,
    specialist_role: str,
    execution_profile: str | None = None,
    *,
    capabilities: tuple[str, ...] | None = None,
    memory_namespace: str | None = None,
    provider_policy: str | None = None,
    resource_limits: ResourceLimits | None = None,
    approval_policy: str | None = None,
    availability_status: str = "enabled",
) -> AgentInstanceSpec:
    catalog = load_agent_catalog()
    definition = catalog.get(specialist_role)
    if definition is None:
        raise ValueError(f"unknown specialist role: {specialist_role}")
    if definition.kind != "specialist":
        raise ValueError(f"{specialist_role} is not a worker specialist")

    profile = execution_profile or definition.execution_profiles[0]
    return AgentInstanceSpec(
        agent_id=agent_id,
        specialist_role=specialist_role,
        execution_profile=profile,
        capabilities=tuple(capabilities if capabilities is not None else definition.capabilities),
        memory_namespace=memory_namespace or f"{definition.memory_namespace}/default",
        provider_policy=provider_policy or definition.provider_policy,
        resource_limits=resource_limits or definition.resource_limits,
        approval_policy=approval_policy or definition.approval_policy,
        availability_status=availability_status,
    )


def _validate_instance(spec: AgentInstanceSpec, catalog: dict[str, AgentDefinition]) -> None:
    if not isinstance(spec, AgentInstanceSpec):
        raise TypeError("manifest entries must be AgentInstanceSpec values")
    if not isinstance(spec.agent_id, str) or _AGENT_ID_PATTERN.fullmatch(spec.agent_id) is None:
        raise ValueError("agent_id must be a stable lowercase identifier")
    definition = catalog.get(spec.specialist_role)
    if definition is None:
        raise ValueError(f"unknown specialist role: {spec.specialist_role}")
    if definition.kind != "specialist":
        raise ValueError(f"{spec.specialist_role} is not a worker specialist")
    if spec.execution_profile not in definition.execution_profiles:
        raise ValueError(
            f"unsupported execution profile {spec.execution_profile!r} for {spec.specialist_role}"
        )
    if (
        not isinstance(spec.capabilities, tuple)
        or not spec.capabilities
        or len(set(spec.capabilities)) != len(spec.capabilities)
        or not set(spec.capabilities).issubset(definition.capabilities)
    ):
        raise ValueError(f"capability escalation or invalid capability set for {spec.specialist_role}")
    namespace_prefix = definition.memory_namespace + "/"
    if (
        not isinstance(spec.memory_namespace, str)
        or not spec.memory_namespace.startswith(namespace_prefix)
        or ".." in spec.memory_namespace
        or "//" in spec.memory_namespace
    ):
        raise ValueError(f"memory namespace is outside the {spec.specialist_role} scope")
    if spec.provider_policy != definition.provider_policy:
        raise ValueError(f"provider policy escalation for {spec.specialist_role}")
    if not isinstance(spec.resource_limits, ResourceLimits):
        raise ValueError("resource_limits must be a ResourceLimits value")
    for field in (
        "timeout_seconds", "memory_mb", "cpu_millis",
        "max_input_bytes", "max_output_bytes", "max_processes",
    ):
        if getattr(spec.resource_limits, field) > getattr(definition.resource_limits, field):
            raise ValueError(f"resource limits exceed the {spec.specialist_role} policy")
    if spec.approval_policy != definition.approval_policy:
        raise ValueError(f"approval policy does not match the {spec.specialist_role} policy")
    if spec.availability_status not in _ALLOWED_STATUSES:
        raise ValueError("availability_status must be enabled or disabled")


def build_agent_registry(manifest: Sequence[AgentInstanceSpec]) -> list[AgentInstanceSpec]:
    """Validate an explicit manifest; never synthesize production identities from a count."""
    if isinstance(manifest, (str, bytes)) or not isinstance(manifest, Sequence):
        raise TypeError("agent registry requires an explicit sequence manifest")

    catalog = load_agent_catalog()
    registered: list[AgentInstanceSpec] = []
    seen_ids: set[str] = set()
    for spec in manifest:
        _validate_instance(spec, catalog)
        if spec.agent_id in seen_ids:
            raise ValueError(f"duplicate agent_id: {spec.agent_id}")
        seen_ids.add(spec.agent_id)
        registered.append(spec)
    return registered


# A single explicit compatibility identity keeps the legacy /agent-run contract working.
# It is a manifest entry, not a generated 391-agent registry or proof of worker execution.
DEFAULT_AGENT_MANIFEST = (
    make_agent_instance_spec("agent-001", "Hermes", "react"),
)
