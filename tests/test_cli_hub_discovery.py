from app.nina import NinaOrchestrator, NinaTask, REGISTERED_TOOLS


def test_cli_hub_discovery_is_a_registered_read_only_capability():
    assert "cli_hub_discover" in REGISTERED_TOOLS

    task = NinaTask.create(
        tenant_id="tenant-cli-hub-test",
        task="Search the CLI-Hub catalogue for image editing tools.",
        requested_tools=["cli_hub_discover"],
    )
    decision = NinaOrchestrator().plan(task)

    assert decision.status == "ALLOW"
    assert decision.allowed_tools == ("cli_hub_discover",)
