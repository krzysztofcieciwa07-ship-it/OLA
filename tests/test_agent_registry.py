from dataclasses import replace

import pytest


def _spec(agent_id, role="Builder", profile=None):
    from app.agent_registry import make_agent_instance_spec

    return make_agent_instance_spec(
        agent_id=agent_id,
        specialist_role=role,
        execution_profile=profile,
    )


def test_catalog_contains_ten_specialists_and_two_control_plane_services():
    from app.agent_registry import load_agent_catalog

    catalog = load_agent_catalog()
    specialists = {name for name, item in catalog.items() if item.kind == "specialist"}
    control_plane = {name for name, item in catalog.items() if item.kind == "control_plane"}

    assert specialists == {
        "Hermes", "Builder", "Scout", "Guardian", "Archivist",
        "Researcher", "Tester", "DevOps", "Sales", "Finance",
    }
    assert control_plane == {"Orchestrator/NINA", "Broker"}


def test_every_specialist_has_profiles_capabilities_and_approval_policy():
    from app.agent_registry import load_agent_catalog

    catalog = load_agent_catalog()
    for name, definition in catalog.items():
        if definition.kind != "specialist":
            continue
        assert definition.execution_profiles, name
        assert set(definition.execution_profiles) <= {
            "codeact", "react", "agentic_rag", "mcp_tool_use",
            "self_reflection", "multi_agent",
        }, name
        assert definition.capabilities, name
        assert definition.approval_policy, name
        assert definition.memory_namespace, name
        assert definition.resource_limits.timeout_seconds > 0, name


def test_registry_rejects_duplicate_agent_ids():
    from app.agent_registry import build_agent_registry

    with pytest.raises(ValueError, match="duplicate agent_id"):
        build_agent_registry([_spec("builder-01"), _spec("builder-01")])


def test_registry_rejects_unknown_specialist_roles():
    from app.agent_registry import build_agent_registry

    invalid = replace(_spec("builder-unknown"), specialist_role="Unknown")
    with pytest.raises(ValueError, match="unknown specialist role"):
        build_agent_registry([invalid])


def test_registry_allows_multiple_instances_of_the_same_specialist():
    from app.agent_registry import build_agent_registry

    agents = build_agent_registry([
        _spec("builder-01", "Builder", "codeact"),
        _spec("builder-02", "Builder", "mcp_tool_use"),
    ])

    assert len(agents) == 2
    assert {agent.role for agent in agents} == {"Builder"}
    assert len({agent.agent_id for agent in agents}) == 2


def test_registry_rejects_unsupported_profile_and_capability_escalation():
    from app.agent_registry import build_agent_registry

    unsupported_profile = replace(_spec("builder-profile"), execution_profile="agentic_rag")
    with pytest.raises(ValueError, match="unsupported execution profile"):
        build_agent_registry([unsupported_profile])

    escalated = replace(_spec("builder-capability"), capabilities=("production.deploy",))
    with pytest.raises(ValueError, match="capability"):
        build_agent_registry([escalated])


def test_registry_rejects_control_plane_services_as_worker_specialists():
    from app.agent_registry import build_agent_registry, make_agent_instance_spec

    with pytest.raises(ValueError, match="not a worker specialist"):
        make_agent_instance_spec("nina-01", "Orchestrator/NINA")


def test_main_uses_an_explicit_manifest_not_a_fabricated_391_id_set():
    import app.main as main_module
    from app.agent_registry import DEFAULT_AGENT_MANIFEST

    assert not hasattr(main_module, "REGISTERED_AGENT_IDS")
    assert set(main_module.AGENT_REGISTRY) == {
        item.agent_id for item in DEFAULT_AGENT_MANIFEST
    }
    assert len(main_module.AGENT_REGISTRY) == len(DEFAULT_AGENT_MANIFEST)
    assert len(main_module.AGENT_REGISTRY) < 391


def test_versioned_manifest_loader_accepts_only_registered_specialist_instances(tmp_path):
    import json
    from app import agent_registry

    assert hasattr(agent_registry, "load_agent_manifest"), "versioned manifest loader is missing"
    manifest_path = tmp_path / "agents.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "agents": [
            {"agent_id": "hermes-001", "specialist_role": "Hermes", "execution_profile": "react"},
            {"agent_id": "builder-001", "specialist_role": "Builder", "execution_profile": "codeact"},
        ],
    }), encoding="utf-8")

    agents = agent_registry.load_agent_manifest(manifest_path)

    assert [agent.agent_id for agent in agents] == ["hermes-001", "builder-001"]
    assert [agent.role for agent in agents] == ["Hermes", "Builder"]


def test_versioned_manifest_loader_rejects_extra_fields_and_duplicate_ids(tmp_path):
    import json
    from app.agent_registry import load_agent_manifest

    manifest_path = tmp_path / "agents.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "agents": [
            {"agent_id": "hermes-001", "specialist_role": "Hermes", "execution_profile": "react", "shell": True},
        ],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest entry"):
        load_agent_manifest(manifest_path)

    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "agents": [
            {"agent_id": "hermes-001", "specialist_role": "Hermes", "execution_profile": "react"},
            {"agent_id": "hermes-001", "specialist_role": "Hermes", "execution_profile": "mcp_tool_use"},
        ],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate agent_id"):
        load_agent_manifest(manifest_path)
