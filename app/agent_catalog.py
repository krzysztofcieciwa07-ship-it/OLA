from dataclasses import dataclass
from typing import Literal


AgentKind = Literal["specialist", "control_plane"]


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    timeout_seconds: int = 120
    memory_mb: int = 512
    cpu_millis: int = 1000
    max_input_bytes: int = 65536
    max_output_bytes: int = 65536
    max_processes: int = 16

    def __post_init__(self):
        values = (
            self.timeout_seconds,
            self.memory_mb,
            self.cpu_millis,
            self.max_input_bytes,
            self.max_output_bytes,
            self.max_processes,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("resource limits must be positive integers")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    name: str
    kind: AgentKind
    description: str
    execution_profiles: tuple[str, ...]
    capabilities: tuple[str, ...]
    memory_namespace: str
    provider_policy: str
    resource_limits: ResourceLimits
    approval_policy: str
    availability_status: str = "enabled"


def load_agent_catalog() -> dict[str, AgentDefinition]:
    """Return the canonical specialist catalogue and separately typed control plane."""
    default = ResourceLimits()
    restricted = ResourceLimits(
        timeout_seconds=90,
        memory_mb=384,
        cpu_millis=750,
        max_input_bytes=32768,
        max_output_bytes=32768,
        max_processes=8,
    )
    read_only = ResourceLimits(
        timeout_seconds=60,
        memory_mb=256,
        cpu_millis=500,
        max_input_bytes=16384,
        max_output_bytes=16384,
        max_processes=4,
    )

    definitions = (
        AgentDefinition(
            name="Hermes",
            kind="specialist",
            description="General operator for bounded, policy-approved task execution.",
            execution_profiles=("react", "mcp_tool_use"),
            capabilities=("agent.run", "task.plan", "tool.safe_expression", "tool.read_only"),
            memory_namespace="agents/hermes",
            provider_policy="run_policy",
            resource_limits=default,
            approval_policy="human_gate_for_side_effects",
        ),
        AgentDefinition(
            name="Builder",
            kind="specialist",
            description="Builds and modifies code within explicitly scoped repositories.",
            execution_profiles=("codeact", "mcp_tool_use"),
            capabilities=("repo.read", "repo.patch", "test.run"),
            memory_namespace="agents/builder",
            provider_policy="code_policy",
            resource_limits=default,
            approval_policy="no_production_deploy_or_secret_change",
        ),
        AgentDefinition(
            name="Scout",
            kind="specialist",
            description="Discovers sources and extracts evidence from allowlisted locations.",
            execution_profiles=("agentic_rag", "mcp_tool_use"),
            capabilities=("source.search", "source.read", "source.cite"),
            memory_namespace="agents/scout",
            provider_policy="allowlisted_sources",
            resource_limits=restricted,
            approval_policy="read_only",
        ),
        AgentDefinition(
            name="Guardian",
            kind="specialist",
            description="Performs independent security and compliance review.",
            execution_profiles=("self_reflection", "agentic_rag"),
            capabilities=("security.read", "policy.audit", "evidence.verify"),
            memory_namespace="agents/guardian",
            provider_policy="local_read_only",
            resource_limits=read_only,
            approval_policy="read_only_never_self_approves",
        ),
        AgentDefinition(
            name="Archivist",
            kind="specialist",
            description="Maintains scoped project memory and append-only project chronicles.",
            execution_profiles=("agentic_rag", "mcp_tool_use"),
            capabilities=("memory.read", "memory.write", "chronicle.append"),
            memory_namespace="agents/archivist",
            provider_policy="local_memory_only",
            resource_limits=restricted,
            approval_policy="cannot_modify_evidence_ledger",
        ),
        AgentDefinition(
            name="Researcher",
            kind="specialist",
            description="Researches and synthesizes source-backed findings.",
            execution_profiles=("agentic_rag", "react", "mcp_tool_use"),
            capabilities=("source.search", "source.read", "analysis.synthesize"),
            memory_namespace="agents/researcher",
            provider_policy="source_provenance_required",
            resource_limits=default,
            approval_policy="read_only_external_actions_require_approval",
        ),
        AgentDefinition(
            name="Tester",
            kind="specialist",
            description="Runs allowlisted tests and reports reproducible results.",
            execution_profiles=("codeact", "mcp_tool_use"),
            capabilities=("test.read", "test.run", "test.report"),
            memory_namespace="agents/tester",
            provider_policy="local_test_only",
            resource_limits=default,
            approval_policy="allowlisted_tests_only",
        ),
        AgentDefinition(
            name="DevOps",
            kind="specialist",
            description="Inspects infrastructure, reliability, and deployment readiness.",
            execution_profiles=("react", "mcp_tool_use"),
            capabilities=("infra.read", "metrics.read", "deploy.request"),
            memory_namespace="agents/devops",
            provider_policy="infrastructure_allowlist",
            resource_limits=default,
            approval_policy="production_mutations_require_human_gate",
        ),
        AgentDefinition(
            name="Sales",
            kind="specialist",
            description="Researches prospects and prepares sales drafts without sending them.",
            execution_profiles=("agentic_rag", "react", "mcp_tool_use"),
            capabilities=("prospect.research", "crm.draft", "message.draft"),
            memory_namespace="agents/sales",
            provider_policy="approved_sales_sources",
            resource_limits=restricted,
            approval_policy="send_or_commitment_requires_human_gate",
        ),
        AgentDefinition(
            name="Finance",
            kind="specialist",
            description="Analyzes financial records and prepares reports without moving funds.",
            execution_profiles=("agentic_rag", "react", "mcp_tool_use"),
            capabilities=("finance.read", "finance.analyze", "report.draft"),
            memory_namespace="agents/finance",
            provider_policy="finance_read_only",
            resource_limits=restricted,
            approval_policy="no_money_movement_refund_or_payment_mutation",
        ),
        AgentDefinition(
            name="Orchestrator/NINA",
            kind="control_plane",
            description="Plans, schedules, and coordinates specialist work under policy.",
            execution_profiles=(),
            capabilities=("agent.schedule", "agent.delegate", "policy.enforce", "handoff.record"),
            memory_namespace="control/nina",
            provider_policy="control_plane_policy_only",
            resource_limits=default,
            approval_policy="cannot_bypass_human_gate_or_igor",
        ),
        AgentDefinition(
            name="Broker",
            kind="control_plane",
            description="Selects an explicitly permitted model provider for each run.",
            execution_profiles=(),
            capabilities=("provider.select", "provider.validate", "provider.provenance"),
            memory_namespace="control/broker",
            provider_policy="provider_allowlist_only",
            resource_limits=read_only,
            approval_policy="cannot_override_run_provider_policy",
        ),
    )
    return {definition.name: definition for definition in definitions}
