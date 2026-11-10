import pytest



def test_391_agent_registry_provides_unique_agent_identities():
    from app.agent_registry import build_agent_registry

    agents = build_agent_registry(391)

    assert len(agents) == 391
    assert len({agent.agent_id for agent in agents}) == 391
    assert len({agent.role for agent in agents}) == 391


def test_391_agent_digest_chain_is_reported_as_simulation_not_cooperation():
    from app.agent_registry import build_agent_registry
    from app.agent_runtime import run_multi_agent_task

    agents = build_agent_registry(391)
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
