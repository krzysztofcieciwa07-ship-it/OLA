from types import SimpleNamespace

import pytest

from app.nina import NinaOrchestrator, NinaTask


def test_cli_hub_discovery_is_a_registered_read_only_capability():
    task = NinaTask.create(
        tenant_id="tenant-cli-hub-test",
        task="Search the CLI-Hub catalogue for image editing tools.",
        requested_tools=["cli_hub_discover"],
    )
    decision = NinaOrchestrator().plan(task)

    assert decision.status == "ALLOW"
    assert decision.allowed_tools == ("cli_hub_discover",)


def test_cli_hub_search_uses_fixed_argv_json_and_restricted_environment(monkeypatch):
    from app import cli_hub_discovery

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        kwargs["stdout"].write(b'{"results":[{"name":"gimp"}]}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_hub_discovery.subprocess, "run", fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-forwarded")

    result = cli_hub_discovery.search_catalog("image editing")

    argv, kwargs = calls[0]
    assert argv == ["cli-hub", "search", "image editing", "--json"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 8
    assert kwargs["env"]["CLI_HUB_NO_ANALYTICS"] == "1"
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert result["catalog"] == {"results": [{"name": "gimp"}]}
    assert result["provider"] == "cli-hub"
    assert result["operation"] == "search"
    assert len(result["output_sha256"]) == 64


def test_cli_hub_search_rejects_invalid_or_oversized_query(monkeypatch):
    from app import cli_hub_discovery

    monkeypatch.setattr(
        cli_hub_discovery.subprocess, "run",
        lambda *args, **kwargs: pytest.fail("process must not start"),
    )
    with pytest.raises(ValueError):
        cli_hub_discovery.search_catalog(" ")
    with pytest.raises(ValueError):
        cli_hub_discovery.search_catalog("x" * 121)


def test_cli_hub_search_fails_closed_when_executable_missing(monkeypatch):
    from app import cli_hub_discovery

    def missing(*args, **kwargs):
        raise FileNotFoundError("cli-hub")

    monkeypatch.setattr(cli_hub_discovery.subprocess, "run", missing)
    with pytest.raises(cli_hub_discovery.CliHubError, match="not installed"):
        cli_hub_discovery.search_catalog("image")


def test_nina_workflow_executes_cli_hub_discovery_through_registered_adapter(monkeypatch):
    from app import cli_hub_discovery
    from app.nina_workflow import execute_registered_node
    from app.workflow_engine import WorkflowNode

    calls = []
    monkeypatch.setattr(
        cli_hub_discovery, "search_catalog",
        lambda query: calls.append(query) or {"provider": "cli-hub", "catalog": []},
    )
    result = execute_registered_node(
        WorkflowNode("catalog", "cli_hub_discover", "search for image tools", ()), {}
    )

    assert calls == ["search for image tools"]
    assert result == {"provider": "cli-hub", "catalog": []}
