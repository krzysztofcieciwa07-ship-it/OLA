import pytest


def _manifest_391():
    from app.agent_registry import load_agent_catalog, make_agent_instance_spec

    catalog = load_agent_catalog()
    roles = [name for name, definition in catalog.items()
             if definition.kind == "specialist"]
    manifest = []
    for index in range(391):
        role = roles[index % len(roles)]
        profiles = catalog[role].execution_profiles
        profile = profiles[index % len(profiles)]
        manifest.append(make_agent_instance_spec(
            agent_id=f"agent-{index + 1:03d}",
            specialist_role=role,
            execution_profile=profile,
        ))
    return manifest


def test_391_agent_registry_uses_unique_ids_and_registered_specialist_roles():
    from app.agent_registry import build_agent_registry, load_agent_catalog

    agents = build_agent_registry(_manifest_391())
    specialists = {
        name for name, definition in load_agent_catalog().items()
        if definition.kind == "specialist"
    }

    assert len(agents) == 391
    assert len({agent.agent_id for agent in agents}) == 391
    assert {agent.role for agent in agents} == specialists
    assert len({agent.role for agent in agents}) == 10


def test_391_agent_digest_chain_is_reported_as_simulation_not_cooperation():
    from app.agent_registry import build_agent_registry
    from app.agent_runtime import run_multi_agent_task

    agents = build_agent_registry(_manifest_391())
    result = run_multi_agent_task("TEST_TENANT", "controlled 391 agent collaboration", agents)

    assert result["status"] == "SIMULATED"
    assert result["execution_mode"] == "digest_only_simulation"
    assert result["agent_count"] == 391
    assert len(result["agent_ids"]) == 391
    assert len(result["digest_edges"]) == 390
    assert result["deterministic_chain_valid"] is True
    assert result["cooperation_verified"] is False
    assert "agent_process_execution" in result["not_established"]
    assert all(item["status"] == "SIMULATED" for item in result["execution"])


def test_multi_agent_simulation_allows_repeated_specialist_roles_but_rejects_duplicate_ids():
    from app.agent_registry import build_agent_registry
    from app.agent_runtime import run_multi_agent_task

    agents = build_agent_registry([
        _manifest_391()[0],
        _manifest_391()[10],
    ])
    result = run_multi_agent_task("TEST_TENANT", "two Hermes instances", agents)
    assert result["agent_count"] == 2
    assert result["cooperation_verified"] is False

    duplicate_ids = [agents[0], agents[0]]
    with pytest.raises(ValueError, match="agent ids must be unique"):
        run_multi_agent_task("TEST_TENANT", "duplicate", duplicate_ids)
