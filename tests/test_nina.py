import pytest

from app.nina import NinaOrchestrator, NinaTask


def test_nina_creates_deterministic_task_contract():
    task = NinaTask.create("tenant-1", "Calculate 17 * 23", ["safe_expression"])
    assert task.tenant_id == "tenant-1"
    assert task.task == "Calculate 17 * 23"
    assert task.requested_tools == ("safe_expression",)
    assert task.task_id


def test_nina_rejects_empty_task():
    with pytest.raises(ValueError, match="task is required"):
        NinaTask.create("tenant-1", "", [])


def test_nina_denies_unknown_tool():
    orchestrator = NinaOrchestrator()
    task = NinaTask.create("tenant-1", "Calculate 17 * 23", ["shell"])
    decision = orchestrator.plan(task)
    assert decision.status == "BLOCK"
    assert decision.allowed_tools == ()
    assert "unknown tool" in decision.reason


def test_nina_allows_registered_tool():
    orchestrator = NinaOrchestrator()
    task = NinaTask.create("tenant-1", "Calculate 17 * 23", ["safe_expression"])
    decision = orchestrator.plan(task)
    assert decision.status == "ALLOW"
    assert decision.allowed_tools == ("safe_expression",)
