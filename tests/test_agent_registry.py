import pytest

from app.agent_catalog import (
    EXECUTION_PROFILE_CAPABILITIES,
    SPECIALIST_ROLE_NAMES,
    load_agent_catalog,
    load_control_plane_catalog,
)
from app.agent_registry import (
    DEFAULT_AGENT_ID,
    DEFAULT_AGENT_MANIFEST,
    AgentInstanceSpec,
    build_agent_registry,
)


def _instance(agent_id="hermes-001", role="Hermes", profile="multi_agent"):
    return AgentInstanceSpec(
        agent_id=agent_id,
        role=role,
        execution_profile=profile,
        configuration=(("fixture", "test"),),
    )


def test_catalog_contains_ten_specialists_and_two_separate_control_plane_services():
    catalog = load_agent_catalog()
    control_plane = load_control_plane_catalog()

    assert tuple(catalog) == SPECIALIST_ROLE_NAMES
    assert len(catalog) == 10
    assert set(control_plane) == {"NINA", "Broker"}
    assert not (set(catalog) & set(control_plane))
    assert all(item.classification == "control_plane" for item in control_plane.values())
    assert control_plane["NINA"].may_orchestrate_specialist_work is True
    assert control_plane["Broker"].may_orchestrate_specialist_work is False
    assert all(not item.may_execute_as_specialist_worker for item in control_plane.values())
    assert all(not item.may_write_evidence_ledger for item in control_plane.values())
    assert all(not item.may_bypass_policy for item in control_plane.values())
    assert all(not item.may_bypass_igor for item in control_plane.values())
    assert all(not item.may_bypass_human_gate for item in control_plane.values())


def test_each_specialist_has_explicit_profile_capability_provider_resource_and_approval_policy():
    catalog = load_agent_catalog()

    assert set(catalog) == set(SPECIALIST_ROLE_NAMES)
    for role, definition in catalog.items():
        assert definition.role == role
        assert definition.description
        assert definition.execution_profiles
        assert set(definition.execution_profiles) <= set(EXECUTION_PROFILE_CAPABILITIES)
        expected_capabilities = {
            EXECUTION_PROFILE_CAPABILITIES[profile]
            for profile in definition.execution_profiles
        }
        assert expected_capabilities <= set(definition.capability_allowlist)
        assert definition.memory_namespace == f"specialists/{role.lower()}"
        assert definition.provider_policy.allowed_providers == ("ollama", "openai")
        assert definition.provider_policy.fallback_allowed is False
        assert definition.resource_limits.cpu_millis > 0
        assert definition.resource_limits.memory_mb > 0
        assert definition.resource_limits.timeout_seconds > 0
        assert definition.resource_limits.measurement_status == "provisional_not_zbook_measured"
        assert definition.approval_policy.human_gate_for_mutating_actions is True
        assert definition.approval_policy.human_gate_for_external_actions is True
        assert definition.approval_policy.self_approval_allowed is False
        assert definition.availability_status == "worker_process_enabled_v1"

    assert catalog["Guardian"].approval_policy.read_only is True
    assert catalog["Guardian"].approval_policy.self_approval_allowed is False


def test_registry_is_manifest_backed_and_allows_repeated_specialist_roles():
    manifest = (
        _instance("hermes-001", "Hermes", "multi_agent"),
        _instance("hermes-002", "Hermes", "react"),
    )

    agents = build_agent_registry(manifest)

    assert [agent.agent_id for agent in agents] == ["hermes-001", "hermes-002"]
    assert [agent.role for agent in agents] == ["Hermes", "Hermes"]
    assert len({agent.agent_id for agent in agents}) == 2


def test_registry_rejects_duplicate_agent_ids():
    with pytest.raises(ValueError, match="duplicate agent_id"):
        build_agent_registry((
            _instance("hermes-001"),
            _instance("hermes-001", "Hermes", "react"),
        ))


def test_registry_rejects_unknown_specialist_roles():
    with pytest.raises(ValueError, match="unknown specialist role"):
        build_agent_registry((_instance("unknown-001", "Unknown", "react"),))


def test_registry_rejects_a_profile_outside_the_specialists_policy():
    with pytest.raises(ValueError, match="not allowed"):
        build_agent_registry((_instance("builder-001", "Builder", "multi_agent"),))


def test_registry_rejects_legacy_count_generation():
    with pytest.raises(TypeError, match="explicit instance manifest"):
        build_agent_registry(391)


def test_default_manifest_is_explicit_and_has_one_stable_instance_per_specialist():
    catalog = load_agent_catalog()
    agents = build_agent_registry(DEFAULT_AGENT_MANIFEST)

    assert len(agents) == 11
    assert len({agent.agent_id for agent in agents}) == 11
    assert {agent.role for agent in agents} == set(catalog)
    assert DEFAULT_AGENT_ID in {agent.agent_id for agent in agents}
    assert any(agent.agent_id == "builder-mcp" and agent.execution_profile == "mcp_tool_use"
               for agent in agents)


def test_main_registers_only_the_explicit_manifest_not_a_synthetic_391_fixture():
    import app.main as main_module

    assert len(main_module.AGENT_INSTANCES_BY_ID) == len(DEFAULT_AGENT_MANIFEST) == 11
    assert DEFAULT_AGENT_ID in main_module.AGENT_INSTANCES_BY_ID
    assert set(main_module.AGENT_CATALOG) == set(SPECIALIST_ROLE_NAMES)
