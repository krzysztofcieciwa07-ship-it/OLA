from dataclasses import dataclass

import pytest

from app.agent_registry import build_agent_registry


SPECIALIST_ROLES = {
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
}


@dataclass(frozen=True)
class ManifestEntry:
    agent_id: str
    role: str
    execution_profile: str
    configuration: tuple[tuple[str, str], ...] = ()


def test_registry_is_manifest_backed_and_allows_repeated_specialist_roles():
    manifest = (
        ManifestEntry("hermes-001", "Hermes", "multi_agent"),
        ManifestEntry("hermes-002", "Hermes", "react"),
    )

    agents = build_agent_registry(manifest)

    assert [agent.agent_id for agent in agents] == ["hermes-001", "hermes-002"]
    assert [agent.role for agent in agents] == ["Hermes", "Hermes"]
    assert len({agent.agent_id for agent in agents}) == 2


def test_registry_rejects_legacy_count_generation():
    with pytest.raises((TypeError, ValueError)):
        build_agent_registry(391)


def test_main_does_not_create_a_fabricated_391_agent_registry_on_import():
    import app.main as main_module

    assert len(main_module.REGISTERED_AGENT_IDS) != 391
