import pytest


def _synthetic_391_manifest():
    from app.agent_catalog import load_agent_catalog
    from app.agent_registry import AgentInstanceSpec

    catalog = load_agent_catalog()
    roles = tuple(catalog)
    manifest = []
    for index in range(391):
        role = roles[index % len(roles)]
        definition = catalog[role]
        profile = definition.execution_profiles[index % len(definition.execution_profiles)]
        manifest.append(AgentInstanceSpec(
            agent_id=f"fixture-agent-{index + 1:03d}",
            role=role,
            execution_profile=profile,
            configuration=(("fixture", "synthetic"),),
        ))
    return tuple(manifest)


def test_391_agent_registry_uses_unique_instance_ids_and_finite_specialist_roles():
    from app.agent_catalog import SPECIALIST_ROLE_NAMES
    from app.agent_registry import build_agent_registry

    agents = build_agent_registry(_synthetic_391_manifest())

    assert len(agents) == 391
    assert len({agent.agent_id for agent in agents}) == 391
    assert set(agent.role for agent in agents) <= set(SPECIALIST_ROLE_NAMES)
    assert len({agent.role for agent in agents}) <= 10
    assert len({agent.role for agent in agents}) < 391


def test_391_agent_digest_chain_is_reported_as_simulation_not_cooperation():
    from app.agent_runtime import run_multi_agent_task
    from app.agent_registry import build_agent_registry

    agents = build_agent_registry(_synthetic_391_manifest())
    result = run_multi_agent_task(
        "TEST_TENANT", "controlled 391 agent collaboration", agents
    )

    assert result["status"] == "SIMULATED"
    assert result["execution_mode"] == "digest_only_simulation"
    assert result["agent_count"] == 391
    assert len(result["agent_ids"]) == 391
    assert len(result["digest_edges"]) == 390
    assert result["deterministic_chain_valid"] is True
    assert result["cooperation_verified"] is False
    assert "agent_process_execution" in result["not_established"]
    assert all(item["status"] == "SIMULATED" for item in result["execution"])
