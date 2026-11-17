from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.ola_watchdog import (
    choose_flow_action,
    decide_verified_flow,
    verify_aggregator_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a" * 40
OLD_SHA = "b" * 40


def flow_run(
    *,
    sha: str = SOURCE_SHA,
    status: str = "completed",
    conclusion: str = "success",
    run_id: int = 123,
    created_at: str = "2026-11-17T08:00:00Z",
) -> dict:
    return {
        "databaseId": run_id,
        "headBranch": "main",
        "headSha": sha,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created_at,
    }


def test_recent_success_on_old_sha_does_not_satisfy_current_main():
    result = choose_flow_action([flow_run(sha=OLD_SHA)], SOURCE_SHA)

    assert result["action"] == "DISPATCH"
    assert result["reason"] == "no_exact_sha_run"


def test_active_flow_is_not_duplicated_even_if_its_sha_is_old():
    result = choose_flow_action(
        [flow_run(sha=OLD_SHA, status="in_progress", conclusion="")],
        SOURCE_SHA,
    )

    assert result["action"] == "WAIT"
    assert result["reason"] == "active_main_flow"


def test_failed_exact_sha_run_is_blocked_not_blindly_retried():
    result = choose_flow_action(
        [flow_run(status="completed", conclusion="failure")],
        SOURCE_SHA,
    )

    assert result["action"] == "BLOCKED"
    assert result["reason"] == "exact_sha_run_failed"


def test_successful_exact_sha_run_requires_artifact_verification():
    result = choose_flow_action([flow_run()], SOURCE_SHA)

    assert result["action"] == "VERIFY"
    assert result["run"]["headSha"] == SOURCE_SHA


def test_verified_flow_is_fresh_or_dispatches_only_after_freshness_window():
    run = flow_run(created_at="2026-11-17T08:00:00Z")

    fresh = decide_verified_flow(
        run,
        evidence_valid=True,
        now_epoch=1794902700,
        freshness_seconds=900,
    )
    stale = decide_verified_flow(
        run,
        evidence_valid=True,
        now_epoch=1794903600,
        freshness_seconds=900,
    )
    invalid = decide_verified_flow(
        run,
        evidence_valid=False,
        now_epoch=1794902700,
        freshness_seconds=900,
    )

    assert fresh["action"] == "HEALTHY"
    assert stale["action"] == "DISPATCH"
    assert invalid["action"] == "BLOCKED"


def valid_summary(source_sha: str = SOURCE_SHA) -> dict:
    return {
        "schema": "ola-auto-evidence-v3",
        "source_commit": source_sha,
        "provider": "ollama",
        "openai_required": False,
        "preflight": "success",
        "real_ollama_full_flow": "success",
        "preflight_artifact_integrity": "VERIFIED",
        "ollama_artifact_integrity": "VERIFIED",
        "independent_igor_artifact_integrity": "VERIFIED",
        "status": "RUNTIME_CHAIN_VERIFIED",
        "verified_claim": True,
        "human_gate": "required_for_terminal_execution",
        "fail_closed": True,
    }


def write_bundle(tmp_path, summary: dict) -> None:
    raw = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "ola-auto-evidence.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / "ola-auto-evidence.sha256").write_text(
        f"{digest}  ola-auto-evidence.json\n",
        encoding="utf-8",
    )


def test_aggregator_bundle_requires_checksum_exact_sha_and_all_evidence(tmp_path):
    write_bundle(tmp_path, valid_summary())

    ok, reason, parsed = verify_aggregator_bundle(tmp_path, SOURCE_SHA)

    assert ok is True
    assert reason == "verified"
    assert parsed["source_commit"] == SOURCE_SHA


def test_aggregator_bundle_rejects_tampering_and_wrong_source(tmp_path):
    write_bundle(tmp_path, valid_summary())
    summary_path = tmp_path / "ola-auto-evidence.json"
    summary_path.write_text(summary_path.read_text() + " ", encoding="utf-8")

    ok, reason, _ = verify_aggregator_bundle(tmp_path, SOURCE_SHA)
    assert ok is False
    assert reason == "summary_checksum_mismatch"

    write_bundle(tmp_path, valid_summary(OLD_SHA))
    ok, reason, _ = verify_aggregator_bundle(tmp_path, SOURCE_SHA)
    assert ok is False
    assert reason == "source_sha_mismatch"


def test_aggregator_bundle_rejects_unverified_or_non_fail_closed_claims(tmp_path):
    summary = valid_summary()
    summary["independent_igor_artifact_integrity"] = "MISSING"
    write_bundle(tmp_path, summary)

    ok, reason, _ = verify_aggregator_bundle(tmp_path, SOURCE_SHA)

    assert ok is False
    assert reason == "evidence_not_verified"


def test_watchdog_workflow_persists_lifecycle_evidence_and_never_cancels_active_run():
    workflow = (
        ROOT / ".github" / "workflows" / "ola-24x7-watchdog.yml"
    ).read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "ola_watchdog.py").read_text(encoding="utf-8")

    assert "cancel-in-progress: false" in workflow
    assert "upload-artifact@" in workflow
    assert "scripts/ola_watchdog.py" in workflow
    assert '"run.start"' in script
    assert '"run.end"' in script
    assert "headSha" in script
    assert "gh run download" in script
    assert "classify" in script
