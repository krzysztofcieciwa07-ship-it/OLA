import pytest



def test_391_agent_registry_provides_unique_agent_identities():
    from app.agent_registry import build_agent_registry

    agents = build_agent_registry(391)

    assert len(agents) == 391
    assert len({agent.agent_id for agent in agents}) == 391
    assert len({agent.role for agent in agents}) == 391


def test_391_digest_simulation_does_not_claim_real_cooperation():
    from app.agent_registry import build_agent_registry
    from app.agent_runtime import run_multi_agent_task

    agents = build_agent_registry(391)
    result = run_multi_agent_task("TEST_TENANT", "controlled 391 agent collaboration", agents)

    assert result["status"] == "SIMULATED"
    assert result["agent_count"] == 391
    assert len(result["agent_ids"]) == 391
    assert len(result["communication_edges"]) >= 390
    assert result["cooperation_verified"] is False
    assert result["digest_structure_verified"] is True
    assert result["answer_correctness"] == "UNKNOWN"
    assert result["real_llm_invocations"] == 0
