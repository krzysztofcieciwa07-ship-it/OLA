"""Typed OLA specialist catalogue and policy contracts.

The catalogue describes policy and intended execution, not proof that a worker
profile is currently isolated or operational on a target workstation.
"""
from dataclasses import dataclass


SPECIALIST_ROLE_NAMES = (
    "Hermes",
    "Builder",
    "Scout",
    "Guardian",
    "Archivist",
    "Researcher",
    "Tester",
    "DevOps",
    "Sales",
    "Finance",
)

EXECUTION_PROFILE_CAPABILITIES = {
    "codeact": "safe_expression",
    "react": "react_loop",
    "agentic_rag": "evidence_retriever",
    "mcp_tool_use": "local_mcp_tool_registry.sha256",
    "self_reflection": "reflection_check",
    "multi_agent": "agent_aggregator",
}


@dataclass(frozen=True)
class ResourceLimits:
    """Provisional upper bounds; not yet measured against the ZBook."""

    cpu_millis: int
    memory_mb: int
    timeout_seconds: int
    max_pids: int
    max_input_bytes: int
    max_output_bytes: int
    measurement_status: str = "provisional_not_zbook_measured"

    def __post_init__(self):
        values = (
            self.cpu_millis,
            self.memory_mb,
            self.timeout_seconds,
            self.max_pids,
            self.max_input_bytes,
            self.max_output_bytes,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("resource limits must be positive integers")
        if self.measurement_status != "provisional_not_zbook_measured":
            raise ValueError("ZBook resource limits require measured preflight evidence")


@dataclass(frozen=True)
class ApprovalPolicy:
    human_gate_for_mutating_actions: bool
    human_gate_for_external_actions: bool
    self_approval_allowed: bool
    read_only: bool = False


@dataclass(frozen=True)
class ProviderPolicy:
    allowed_providers: tuple[str, ...]
    fallback_allowed: bool = False

    def __post_init__(self):
        if not self.allowed_providers:
            raise ValueError("provider policy must allow at least one provider")
        if any(provider not in {"ollama", "openai"} for provider in self.allowed_providers):
            raise ValueError("provider policy contains an unsupported provider")
        if self.fallback_allowed:
            raise ValueError("provider fallback is disabled for the ZBook profile")


@dataclass(frozen=True)
class AgentDefinition:
    role: str
    description: str
    execution_profiles: tuple[str, ...]
    capability_allowlist: tuple[str, ...]
    memory_namespace: str
    provider_policy: ProviderPolicy
    resource_limits: ResourceLimits
    approval_policy: ApprovalPolicy
    availability_status: str


@dataclass(frozen=True)
class ControlPlaneServiceDefinition:
    service_name: str
    description: str
    classification: str
    may_orchestrate_specialist_work: bool
    may_execute_as_specialist_worker: bool
    may_write_evidence_ledger: bool
    may_bypass_policy: bool
    may_bypass_igor: bool
    may_bypass_human_gate: bool


_DEFAULT_RESOURCE_LIMITS = ResourceLimits(
    cpu_millis=500,
    memory_mb=512,
    timeout_seconds=30,
    max_pids=16,
    max_input_bytes=16_384,
    max_output_bytes=65_536,
)

_DEFAULT_APPROVAL_POLICY = ApprovalPolicy(
    human_gate_for_mutating_actions=True,
    human_gate_for_external_actions=True,
    self_approval_allowed=False,
)

_ZBOOK_PROVIDER_POLICY = ProviderPolicy(
    allowed_providers=("ollama",),
    fallback_allowed=False,
)

# This describes the currently available compatibility path only. Task 2
# replaces it with isolated workers; "catalogued" is not a claim of autonomy.
_LEGACY_AVAILABILITY = "catalogued_legacy_pipeline_only"


_AGENT_CATALOG = {
    "Hermes": AgentDefinition(
        role="Hermes",
        description="General specialist coordinator for bounded, policy-approved subtasks.",
        execution_profiles=("multi_agent", "react"),
        capability_allowlist=("agent_aggregator", "react_loop"),
        memory_namespace="specialists/hermes",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=_DEFAULT_APPROVAL_POLICY,
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Builder": AgentDefinition(
        role="Builder",
        description="Build and code-analysis specialist; no deployment or secret mutation capability.",
        execution_profiles=("codeact", "mcp_tool_use"),
        capability_allowlist=("safe_expression", "local_mcp_tool_registry.sha256"),
        memory_namespace="specialists/builder",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=_DEFAULT_APPROVAL_POLICY,
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Scout": AgentDefinition(
        role="Scout",
        description="Read-only discovery specialist for bounded evidence retrieval and observation.",
        execution_profiles=("react", "agentic_rag"),
        capability_allowlist=("react_loop", "evidence_retriever"),
        memory_namespace="specialists/scout",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Guardian": AgentDefinition(
        role="Guardian",
        description="Independent read-only policy and evidence reviewer; cannot self-approve findings.",
        execution_profiles=("agentic_rag", "self_reflection"),
        capability_allowlist=("evidence_retriever", "reflection_check"),
        memory_namespace="specialists/guardian",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Archivist": AgentDefinition(
        role="Archivist",
        description="Read-only evidence retrieval and integrity-inspection specialist.",
        execution_profiles=("agentic_rag", "mcp_tool_use"),
        capability_allowlist=("evidence_retriever", "local_mcp_tool_registry.sha256"),
        memory_namespace="specialists/archivist",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Researcher": AgentDefinition(
        role="Researcher",
        description="Research specialist restricted to observation and tenant-scoped evidence retrieval.",
        execution_profiles=("react", "agentic_rag"),
        capability_allowlist=("react_loop", "evidence_retriever"),
        memory_namespace="specialists/researcher",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Tester": AgentDefinition(
        role="Tester",
        description="Test specialist for bounded expression checks and output reflection.",
        execution_profiles=("codeact", "self_reflection"),
        capability_allowlist=("safe_expression", "reflection_check"),
        memory_namespace="specialists/tester",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=_DEFAULT_APPROVAL_POLICY,
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "DevOps": AgentDefinition(
        role="DevOps",
        description="Read-only operations-analysis specialist; production changes require a separate Human Gate.",
        execution_profiles=("react", "agentic_rag"),
        capability_allowlist=("react_loop", "evidence_retriever"),
        memory_namespace="specialists/devops",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Sales": AgentDefinition(
        role="Sales",
        description="Read-only commercial-analysis specialist; cannot send communications or make commitments.",
        execution_profiles=("react", "agentic_rag"),
        capability_allowlist=("react_loop", "evidence_retriever"),
        memory_namespace="specialists/sales",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
    "Finance": AgentDefinition(
        role="Finance",
        description="Read-only finance-analysis specialist; cannot move money or change payment state.",
        execution_profiles=("codeact", "agentic_rag"),
        capability_allowlist=("safe_expression", "evidence_retriever"),
        memory_namespace="specialists/finance",
        provider_policy=_ZBOOK_PROVIDER_POLICY,
        resource_limits=_DEFAULT_RESOURCE_LIMITS,
        approval_policy=ApprovalPolicy(True, True, False, read_only=True),
        availability_status=_LEGACY_AVAILABILITY,
    ),
}


_CONTROL_PLANE_CATALOG = {
    "NINA": ControlPlaneServiceDefinition(
        service_name="NINA",
        description="Trusted task orchestration and policy control plane.",
        classification="control_plane",
        may_orchestrate_specialist_work=True,
        may_execute_as_specialist_worker=False,
        may_write_evidence_ledger=False,
        may_bypass_policy=False,
        may_bypass_igor=False,
        may_bypass_human_gate=False,
    ),
    "Broker": ControlPlaneServiceDefinition(
        service_name="Broker",
        description="Provider broker enforcing each run's immutable provider policy.",
        classification="control_plane",
        may_orchestrate_specialist_work=False,
        may_execute_as_specialist_worker=False,
        may_write_evidence_ledger=False,
        may_bypass_policy=False,
        may_bypass_igor=False,
        may_bypass_human_gate=False,
    ),
}


def load_agent_catalog() -> dict[str, AgentDefinition]:
    """Return the ten worker-specialist definitions; control-plane services are separate."""
    return dict(_AGENT_CATALOG)


def load_control_plane_catalog() -> dict[str, ControlPlaneServiceDefinition]:
    """Return NINA and Broker as control-plane services, not worker specialists."""
    return dict(_CONTROL_PLANE_CATALOG)
