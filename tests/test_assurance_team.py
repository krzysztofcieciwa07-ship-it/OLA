import subprocess
import sys
from pathlib import Path

from app.assurance_team.contracts import (
    AgentContext,
    AgentReport,
    AgentStatus,
    verify_event_chain,
)
from app.assurance_team.orchestrator import AgentOrchestrator
from app.assurance_team.tester import TEST_PATHS, TesterAgent


def _context(tmp_path):
    return AgentContext(repo_root=tmp_path, source_commit="a" * 40)


def test_tester_runs_only_allowlisted_runtime_test_suites(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="12 passed in 0.10s\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = TesterAgent().run(_context(tmp_path))

    assert result.role == "tester"
    assert result.status == AgentStatus.PASS
    assert calls
    command, kwargs = calls[0]
    assert command[:3] == [sys.executable, "-m", "pytest"]
    assert command[3] == "-q"
    assert command[4:] == list(TEST_PATHS)
    assert kwargs["cwd"] == tmp_path
    assert kwargs["shell"] is False
    assert kwargs["timeout"] > 0
    assert result.metrics["test_paths"] == list(TEST_PATHS)
    assert result.metrics["output_sha256"]
    assert result.metrics["summary"] == "12 passed in 0.10s"


def test_tester_fails_closed_on_timeout(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    result = TesterAgent().run(_context(tmp_path))

    assert result.status == AgentStatus.FAIL
    assert any(item.code == "TEST_SUITE_TIMEOUT" for item in result.findings)


def test_orchestrator_runs_agents_in_order_and_records_complete_lifecycle(tmp_path):
    order = []

    class StubAgent:
        def __init__(self, role, status=AgentStatus.PASS):
            self.role = role
            self.status = status

        def run(self, context):
            order.append(self.role)
            return AgentReport(
                role=self.role,
                status=self.status,
                findings=[],
                metrics={"source_commit": context.source_commit},
            )

    runner = AgentOrchestrator(
        agents=[StubAgent("tester"), StubAgent("architecture")],
        planned_roles=["tester", "architecture", "performance", "protection", "legal"],
    )
    report = runner.run(_context(tmp_path))

    assert order == ["tester", "architecture"]
    assert report["source_commit"] == "a" * 40
    assert report["status"] == "PASS"
    assert report["coverage"]["enabled"] == ["tester", "architecture"]
    assert report["coverage"]["not_enabled"] == ["performance", "protection", "legal"]
    assert [event["event_type"] for event in report["events"]] == [
        "run.start",
        "agent.start",
        "agent.end",
        "agent.start",
        "agent.end",
        "run.end",
    ]
    assert verify_event_chain(report["events"])


def test_orchestrator_continues_after_agent_failure_but_marks_run_failed(tmp_path):
    order = []

    class StubAgent:
        def __init__(self, role, status):
            self.role = role
            self.status = status

        def run(self, context):
            order.append(self.role)
            return AgentReport(role=self.role, status=self.status)

    runner = AgentOrchestrator(
        agents=[
            StubAgent("tester", AgentStatus.FAIL),
            StubAgent("architecture", AgentStatus.PASS),
        ],
        planned_roles=["tester", "architecture"],
    )
    report = runner.run(_context(tmp_path))

    assert order == ["tester", "architecture"]
    assert report["status"] == "FAIL"
    assert report["agent_results"][0]["status"] == "FAIL"
    assert report["agent_results"][1]["status"] == "PASS"


def test_event_chain_detects_mutated_event_payload(tmp_path):
    class StubAgent:
        role = "tester"

        def run(self, context):
            return AgentReport(role=self.role, status=AgentStatus.PASS)

    report = AgentOrchestrator(
        agents=[StubAgent()],
        planned_roles=["tester"],
    ).run(_context(tmp_path))

    mutated = [dict(event) for event in report["events"]]
    mutated[1]["payload"] = {"role": "protection"}

    assert verify_event_chain(mutated) is False

def test_agent_context_rejects_non_integer_timeout(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="integer"):
        AgentContext(repo_root=tmp_path, source_commit="a" * 40, timeout_seconds=1.5)


def test_cli_writes_json_report_event_ledger_and_digest(monkeypatch, tmp_path):
    import json
    from app.assurance_team import cli

    class PassingAgent:
        role = "tester"

        def run(self, context):
            return AgentReport(
                role=self.role,
                status=AgentStatus.PASS,
                metrics={"source_commit": context.source_commit},
            )

    monkeypatch.setattr(cli, "TesterAgent", PassingAgent)
    output_dir = tmp_path / "artifacts"
    exit_code = cli.main([
        "--repo-root", str(tmp_path),
        "--source-commit", "b" * 40,
        "--output-dir", str(output_dir),
    ])

    assert exit_code == 0
    report = json.loads((output_dir / "team-report.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (output_dir / "team-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    manifest = (output_dir / "team-evidence.sha256").read_text(encoding="utf-8")

    assert report["source_commit"] == "b" * 40
    assert report["status"] == "PASS"
    assert report["coverage"]["coverage_status"] == "PARTIAL"
    assert report["coverage"]["not_enabled"] == ["architecture", "performance", "protection", "legal"]
    assert verify_event_chain(events)
    assert len(manifest.splitlines()) == 2
