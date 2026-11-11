import copy
import hashlib
import os
import sys
import time

import pytest

from scripts.agent_team import (
    AGENT_ORDER,
    AgentTeamError,
    aggregate_reports,
    build_agent_report,
    verify_report_integrity,
)


SOURCE_COMMIT = "a" * 40
RUN_ID = "42950000000"


def make_report(agent_id, status="PASS", source_commit=SOURCE_COMMIT, run_attempt=1):
    return build_agent_report(
        agent_id=agent_id,
        source_commit=source_commit,
        run_id=RUN_ID,
        run_attempt=run_attempt,
        status=status,
        checks=[{"check_id": "contract", "status": status}],
        started_at="2026-11-11T08:00:00+00:00",
        completed_at="2026-11-11T08:00:01+00:00",
        duration_ms=1000,
    )


def test_agent_order_is_explicit_and_sequential():
    assert AGENT_ORDER == (
        "tester",
        "architecture",
        "performance",
        "security",
        "legal",
    )


def test_report_is_bound_to_commit_run_and_integrity_digest():
    report = make_report("tester")

    assert report["source_commit"] == SOURCE_COMMIT
    assert report["run_id"] == RUN_ID
    assert report["run_attempt"] == 1
    assert verify_report_integrity(report)

    changed = copy.deepcopy(report)
    changed["checks"][0]["status"] = "FAIL"
    assert not verify_report_integrity(changed)


def test_report_rejects_unknown_agent_and_malformed_commit():
    with pytest.raises(AgentTeamError, match="unknown agent"):
        make_report("invented-agent")

    with pytest.raises(AgentTeamError, match="full lowercase 40-character"):
        make_report("tester", source_commit="abc123")


def test_aggregator_passes_only_when_every_agent_passes():
    reports = [make_report(agent_id) for agent_id in AGENT_ORDER]

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "PASS"
    assert manifest["execution_order"] == list(AGENT_ORDER)
    assert manifest["orchestrator"]["status"] == "PASS"
    assert verify_report_integrity(manifest)


def test_legal_review_never_becomes_automatic_compliance_pass():
    reports = [
        make_report(agent_id, status="REVIEW" if agent_id == "legal" else "PASS")
        for agent_id in AGENT_ORDER
    ]

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "REVIEW_REQUIRED"
    assert manifest["orchestrator"]["status"] == "REVIEW_REQUIRED"
    assert manifest["agents"]["legal"]["status"] == "REVIEW"


def test_cli_returns_nonzero_for_review_required(monkeypatch, tmp_path, capsys):
    from scripts import agent_team

    review_manifest = {
        "overall_status": "REVIEW_REQUIRED",
        "agents": {},
        "issues": [],
    }
    monkeypatch.setattr(
        agent_team,
        "aggregate_from_directory",
        lambda **kwargs: review_manifest,
    )

    exit_code = agent_team.main([
        "aggregate",
        "--reports-dir", str(tmp_path / "reports"),
        "--source-commit", SOURCE_COMMIT,
        "--run-id", RUN_ID,
        "--run-attempt", "1",
        "--output", str(tmp_path / "manifest.json"),
    ])

    assert exit_code == 1
    assert '"overall_status": "REVIEW_REQUIRED"' in capsys.readouterr().out


def test_missing_agent_blocks_aggregate():
    reports = [make_report(agent_id) for agent_id in AGENT_ORDER[:-1]]

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "BLOCKED"
    assert "legal" in manifest["missing_agents"]


def test_source_commit_mismatch_blocks_aggregate():
    reports = [
        make_report(
            agent_id,
            source_commit=("b" * 40 if agent_id == "security" else SOURCE_COMMIT),
        )
        for agent_id in AGENT_ORDER
    ]

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "BLOCKED"
    assert any("source commit mismatch" in issue for issue in manifest["issues"])


def test_tampered_report_blocks_aggregate():
    reports = [make_report(agent_id) for agent_id in AGENT_ORDER]
    reports[0]["checks"][0]["status"] = "FAIL"

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "BLOCKED"
    assert any("integrity" in issue for issue in manifest["issues"])


def test_agent_failure_blocks_aggregate_even_if_other_agents_pass():
    reports = [
        make_report(agent_id, status="FAIL" if agent_id == "tester" else "PASS")
        for agent_id in AGENT_ORDER
    ]

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "BLOCKED"
    assert manifest["agents"]["tester"]["status"] == "FAIL"


def test_command_check_bounds_capture_but_hashes_complete_output(tmp_path):
    from scripts.agent_team import MAX_CAPTURE_BYTES, _command_check

    output_size = MAX_CAPTURE_BYTES + 12345
    result = _command_check(
        "bounded_output",
        (sys.executable, "-c", f"import sys; sys.stdout.write('x' * {output_size})"),
        10,
        repo_root=tmp_path,
        env=os.environ.copy(),
    )

    assert result["status"] == "PASS"
    assert result["stdout_bytes"] == output_size
    assert result["stdout_truncated"] is True
    assert len(result["stdout_excerpt"]) <= 4000
    assert result["stdout_sha256"] == hashlib.sha256(b"x" * output_size).hexdigest()


def test_command_check_timeout_fails_and_cleans_up(tmp_path):
    from scripts.agent_team import _command_check

    result = _command_check(
        "timeout",
        (sys.executable, "-c", "import time; time.sleep(5)"),
        0.1,
        repo_root=tmp_path,
        env=os.environ.copy(),
    )

    assert result["status"] == "FAIL"
    assert result["error"] == "timeout after 0.1 seconds"


def test_resolve_repo_path_rejects_symlink_escape(tmp_path):
    from scripts.agent_team import _resolve_repo_path

    repo_root = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo_root.mkdir()
    outside.mkdir()
    (repo_root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(AgentTeamError, match="inside the repository"):
        _resolve_repo_path("linked/report.json", repo_root)


def test_mixed_run_attempts_block_aggregate():
    reports = [
        make_report(agent_id, run_attempt=2 if agent_id == "security" else 1)
        for agent_id in AGENT_ORDER
    ]

    manifest = aggregate_reports(
        reports,
        expected_source_commit=SOURCE_COMMIT,
        expected_run_id=RUN_ID,
        expected_run_attempt=1,
    )

    assert manifest["overall_status"] == "BLOCKED"
    assert any("run attempt mismatch for security" in issue for issue in manifest["issues"])


def test_command_check_kills_timed_out_descendant_process_group(tmp_path):
    from scripts.agent_team import _command_check

    marker = tmp_path / "orphan-survived.txt"
    child_code = (
        "import pathlib,time; time.sleep(0.6); "
        f"pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(10)"
    )

    result = _command_check(
        "descendant_timeout",
        (sys.executable, "-c", parent_code),
        0.2,
        repo_root=tmp_path,
        env=os.environ.copy(),
    )
    time.sleep(0.8)

    assert result["status"] == "FAIL"
    assert result["error"] == "timeout after 0.2 seconds"
    assert not marker.exists()


def test_aggregator_rejects_report_symlink_escape(tmp_path):
    from scripts.agent_team import aggregate_from_directory

    repo_root = tmp_path / "repo"
    reports_dir = repo_root / "reports"
    outside_dir = tmp_path / "outside"
    reports_dir.mkdir(parents=True)
    outside_dir.mkdir()
    outside_report = outside_dir / "agent-tester.json"
    outside_report.write_text("{}", encoding="utf-8")
    (reports_dir / "agent-tester.json").symlink_to(outside_report)

    with pytest.raises(AgentTeamError, match="report path escapes the repository"):
        aggregate_from_directory(
            reports_dir="reports",
            expected_source_commit=SOURCE_COMMIT,
            expected_run_id=RUN_ID,
            expected_run_attempt=1,
            output_path="manifest.json",
            repo_root=repo_root,
        )

