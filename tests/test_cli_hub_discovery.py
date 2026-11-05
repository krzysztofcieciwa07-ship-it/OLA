import json

import pytest

from app.nina import NinaOrchestrator, NinaTask


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield from self.chunks


def _registry():
    return {
        "meta": {"updated": "2026-06-19"},
        "clis": [
            {
                "name": "gimp",
                "display_name": "GIMP",
                "version": "1.0.0",
                "description": "Image editing and raster graphics",
                "category": "image",
                "requires": "GIMP installed",
                "install_cmd": "UNTRUSTED INSTALL INSTRUCTION",
            },
            {
                "name": "blender",
                "display_name": "Blender",
                "version": "1.0.0",
                "description": "3D modeling and rendering",
                "category": "3d",
            },
        ],
    }


def test_cli_hub_discovery_is_a_registered_read_only_capability():
    task = NinaTask.create(
        tenant_id="tenant-cli-hub-test",
        task="image editing",
        requested_tools=["cli_hub_discover"],
    )
    decision = NinaOrchestrator().plan(task)

    assert decision.status == "ALLOW"
    assert decision.allowed_tools == ("cli_hub_discover",)


def test_cli_hub_search_reads_registry_and_filters_without_exposing_install_commands(monkeypatch):
    from app import cli_hub_discovery

    raw = json.dumps(_registry()).encode()
    calls = []

    def fake_stream(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse([raw[:30], raw[30:]])

    monkeypatch.setattr(cli_hub_discovery.httpx, "stream", fake_stream)
    result = cli_hub_discovery.search_catalog("image editing")

    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == cli_hub_discovery.REGISTRY_URL
    assert kwargs["follow_redirects"] is False
    assert kwargs["headers"]["Accept"] == "application/json"
    assert result["match_count"] == 1
    assert result["matches"][0]["name"] == "gimp"
    assert "install_cmd" not in result["matches"][0]
    assert "UNTRUSTED INSTALL INSTRUCTION" not in repr(result)
    assert len(result["registry_sha256"]) == 64


def test_cli_hub_search_rejects_invalid_or_oversized_query(monkeypatch):
    from app import cli_hub_discovery

    monkeypatch.setattr(
        cli_hub_discovery.httpx, "stream",
        lambda *args, **kwargs: pytest.fail("network request must not start"),
    )
    with pytest.raises(ValueError):
        cli_hub_discovery.search_catalog(" ")
    with pytest.raises(ValueError):
        cli_hub_discovery.search_catalog("x" * 121)


def test_cli_hub_search_rejects_oversized_registry(monkeypatch):
    from app import cli_hub_discovery

    monkeypatch.setattr(
        cli_hub_discovery.httpx, "stream",
        lambda *args, **kwargs: FakeResponse([b"x" * (cli_hub_discovery.MAX_REGISTRY_BYTES + 1)]),
    )
    with pytest.raises(cli_hub_discovery.CliHubError, match="exceeds"):
        cli_hub_discovery.search_catalog("image")


def test_cli_hub_search_rejects_invalid_registry_schema(monkeypatch):
    from app import cli_hub_discovery

    monkeypatch.setattr(
        cli_hub_discovery.httpx, "stream",
        lambda *args, **kwargs: FakeResponse([b'{"items": []}']),
    )
    with pytest.raises(cli_hub_discovery.CliHubError, match="schema"):
        cli_hub_discovery.search_catalog("image")


def test_nina_execute_runs_only_read_only_cli_hub_discovery(monkeypatch):
    from app import cli_hub_discovery
    import app.nina as nina_module

    calls = []
    monkeypatch.setattr(
        cli_hub_discovery, "search_catalog",
        lambda query: calls.append(query) or {"provider": "cli-hub", "matches": []},
    )
    monkeypatch.setattr(
        nina_module, "run_agent_task",
        lambda *args, **kwargs: pytest.fail("general executor must not run"),
    )
    task = NinaTask.create("tenant-cli-hub-test", "image editing", ["cli_hub_discover"])
    result = NinaOrchestrator().execute(task)

    assert calls == ["image editing"]
    assert result["status"] == "COMPLETED_UNVERIFIED"
    assert result["verified"] is False
    assert result["result"]["provider"] == "cli-hub"


def test_nina_blocks_mixed_cli_hub_and_other_capabilities(monkeypatch):
    from app import cli_hub_discovery

    monkeypatch.setattr(
        cli_hub_discovery, "search_catalog",
        lambda *args, **kwargs: pytest.fail("mixed capabilities must not execute"),
    )
    task = NinaTask.create(
        "tenant-cli-hub-test", "image editing", ["cli_hub_discover", "llm_agent"]
    )
    result = NinaOrchestrator().execute(task)

    assert result["status"] == "BLOCK"


def test_nina_workflow_executes_cli_hub_discovery_through_registered_adapter(monkeypatch):
    from app import cli_hub_discovery
    from app.nina_workflow import execute_registered_node
    from app.workflow_engine import WorkflowNode

    calls = []
    monkeypatch.setattr(
        cli_hub_discovery, "search_catalog",
        lambda query: calls.append(query) or {"provider": "cli-hub", "matches": []},
    )
    result = execute_registered_node(
        WorkflowNode("catalog", "cli_hub_discover", "search for image tools", ()), {}
    )

    assert calls == ["search for image tools"]
    assert result == {"provider": "cli-hub", "matches": []}
