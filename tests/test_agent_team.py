import copy

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
    )

    assert manifest["overall_status"] == "BLOCKED"
    assert manifest["agents"]["tester"]["status"] == "FAIL"


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
