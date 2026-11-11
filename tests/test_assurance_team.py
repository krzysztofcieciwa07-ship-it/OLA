import subprocess
import sys
from pathlib import Path

from app.assurance_team.architecture import ArchitectureAgent
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
    assert command[3:] == list(TEST_PATHS)
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

    class PassingArchitectureAgent:
        role = "architecture"

        def run(self, context):
            return AgentReport(
                role=self.role,
                status=AgentStatus.PASS,
                metrics={"source_commit": context.source_commit},
            )

    monkeypatch.setattr(cli, "TesterAgent", PassingAgent)
    monkeypatch.setattr(cli, "ArchitectureAgent", PassingArchitectureAgent)
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
    assert report["coverage"]["enabled"] == ["tester", "architecture"]
    assert report["coverage"]["not_enabled"] == ["performance", "protection", "legal"]
    assert verify_event_chain(events)
    assert len(manifest.splitlines()) == 2

    repo_root = Path(__file__).resolve().parents[1]
    verifier = repo_root / "scripts" / "verify_assurance_team.py"
    verify = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--report", str(output_dir / "team-report.json"),
            "--events", str(output_dir / "team-events.jsonl"),
            "--manifest", str(output_dir / "team-evidence.sha256"),
            "--expected-commit", "b" * 40,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
        check=False,
    )
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["status"] == "VERIFIED"

    events_path = output_dir / "team-events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8").replace('"role":"tester"', '"role":"protection"', 1),
        encoding="utf-8",
    )
    tamper_check = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--report", str(output_dir / "team-report.json"),
            "--events", str(events_path),
            "--manifest", str(output_dir / "team-evidence.sha256"),
            "--expected-commit", "b" * 40,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
        check=False,
    )
    assert tamper_check.returncode == 1


def test_tester_returns_unknown_when_success_has_no_recognized_summary(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="........", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = TesterAgent().run(_context(tmp_path))

    assert result.status == AgentStatus.UNKNOWN
    assert any(item.code == "TEST_SUMMARY_UNRECOGNIZED" for item in result.findings)


def test_tester_reports_unknown_when_all_tests_are_skipped(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="10 skipped in 0.10s\\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = TesterAgent().run(_context(tmp_path))

    assert result.status == AgentStatus.UNKNOWN
    assert any(item.code == "TESTS_NOT_EXECUTED" for item in result.findings)


def test_tester_parses_pytest_summary_from_stderr(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="7 passed, 1 skipped in 0.20s\\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = TesterAgent().run(_context(tmp_path))

    assert result.status == AgentStatus.PASS
    assert result.metrics["summary"] == "7 passed, 1 skipped in 0.20s"
    assert result.metrics["counts"]["passed"] == 7
    assert result.metrics["counts"]["skipped"] == 1


def _architecture_project(tmp_path, files):
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "__init__.py").write_text("", encoding="utf-8")
    for relative_path, source in files.items():
        target = app_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return tmp_path


def test_architecture_agent_accepts_acyclic_internal_imports(tmp_path):
    root = _architecture_project(tmp_path, {
        "main.py": "from .service import execute\n",
        "service.py": "def execute():\n    return True\n",
    })

    report = ArchitectureAgent().run(AgentContext(repo_root=root, source_commit="c" * 40))

    assert report.role == "architecture"
    assert report.status == AgentStatus.PASS
    assert report.metrics["module_count"] == 3
    assert report.metrics["module_level_import_edges"] == 1
    assert not report.findings


def test_architecture_agent_detects_module_level_import_cycle(tmp_path):
    root = _architecture_project(tmp_path, {
        "a.py": "from .b import B\n",
        "b.py": "from .a import A\n",
    })

    report = ArchitectureAgent().run(AgentContext(repo_root=root, source_commit="c" * 40))

    assert report.status == AgentStatus.FAIL
    assert any(item.code == "ARCH_IMPORT_CYCLE" for item in report.findings)


def test_architecture_agent_detects_application_dependency_on_api_composition_root(tmp_path):
    root = _architecture_project(tmp_path, {
        "main.py": "app = object()\n",
        "service.py": "def execute():\n    from .main import app\n    return app\n",
    })

    report = ArchitectureAgent().run(AgentContext(repo_root=root, source_commit="c" * 40))

    assert report.status == AgentStatus.FAIL
    assert any(item.code == "ARCH_API_COMPOSITION_ROOT_IMPORT" for item in report.findings)


def test_architecture_agent_detects_unresolved_internal_import(tmp_path):
    root = _architecture_project(tmp_path, {
        "service.py": "from .missing_module import execute\n",
    })

    report = ArchitectureAgent().run(AgentContext(repo_root=root, source_commit="c" * 40))

    assert report.status == AgentStatus.FAIL
    assert any(item.code == "ARCH_UNRESOLVED_INTERNAL_IMPORT" for item in report.findings)


def test_architecture_agent_reports_python_syntax_errors(tmp_path):
    root = _architecture_project(tmp_path, {
        "service.py": "def execute(:\n    return True\n",
    })

    report = ArchitectureAgent().run(AgentContext(repo_root=root, source_commit="c" * 40))

    assert report.status == AgentStatus.FAIL
    assert any(item.code == "ARCH_SYNTAX_ERROR" for item in report.findings)


def test_architecture_agent_does_not_treat_function_local_import_as_import_time_cycle(tmp_path):
    root = _architecture_project(tmp_path, {
        "a.py": "from .b import B\n",
        "b.py": "def load():\n    from .a import A\n    return A\n",
    })

    report = ArchitectureAgent().run(AgentContext(repo_root=root, source_commit="c" * 40))

    assert report.status == AgentStatus.PASS
    assert report.metrics["module_level_import_edges"] == 1
    assert report.metrics["deferred_imports"] == 1
