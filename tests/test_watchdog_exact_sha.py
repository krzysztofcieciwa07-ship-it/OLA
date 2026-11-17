from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from scripts.ola_watchdog import (
    choose_flow_action,
    decide_verified_flow,
    run_watchdog,
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
    updated_at: str | None = None,
) -> dict:
    return {
        "databaseId": run_id,
        "headBranch": "main",
        "headSha": sha,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created_at,
        "updatedAt": updated_at or created_at,
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


def test_verified_flow_freshness_uses_completion_update_not_start_time():
    run = flow_run(
        created_at="2026-11-17T08:00:00Z",
        updated_at="2026-11-17T08:25:00Z",
    )

    fresh = decide_verified_flow(
        run,
        evidence_valid=True,
        now_epoch=1794904200,
        freshness_seconds=900,
    )
    stale = decide_verified_flow(
        run,
        evidence_valid=True,
        now_epoch=1794904900,
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



def install_fake_gh(tmp_path, monkeypatch, payload: bytes) -> None:
    import base64

    encoded = base64.b64encode(payload).decode("ascii")
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        f"#!{sys.executable}\n"
        "import base64, sys\n"
        f"sys.stdout.buffer.write(base64.b64decode({encoded!r}))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))


def test_artifact_archive_digest_is_checked_before_safe_extraction(tmp_path, monkeypatch):
    import io
    import zipfile

    from scripts.ola_watchdog import download_and_verify_artifact_archive

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("ola-auto-evidence.json", "{}")
    archive_bytes = archive.getvalue()
    archive_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()

    install_fake_gh(tmp_path, monkeypatch, archive_bytes)
    destination = tmp_path / "extracted"

    ok, reason = download_and_verify_artifact_archive(
        "example/OLA", 42, archive_digest, len(archive_bytes), destination
    )
    assert ok is True
    assert reason == "verified"
    assert (destination / "ola-auto-evidence.json").read_text() == "{}"

    size_ok, size_reason = download_and_verify_artifact_archive(
        "example/OLA", 42, archive_digest, len(archive_bytes) + 1, tmp_path / "wrong-size"
    )
    assert size_ok is False
    assert size_reason == "aggregator_artifact_archive_size_mismatch"

    bad_ok, bad_reason = download_and_verify_artifact_archive(
        "example/OLA", 42, "sha256:" + ("0" * 64), len(archive_bytes), tmp_path / "bad"
    )
    assert bad_ok is False
    assert bad_reason == "aggregator_artifact_archive_digest_mismatch"


def test_artifact_archive_rejects_path_traversal(tmp_path, monkeypatch):
    import io
    import zipfile

    from scripts.ola_watchdog import download_and_verify_artifact_archive

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "unsafe")
    archive_bytes = archive.getvalue()
    archive_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()

    install_fake_gh(tmp_path, monkeypatch, archive_bytes)
    ok, reason = download_and_verify_artifact_archive(
        "example/OLA", 42, archive_digest, len(archive_bytes), tmp_path / "extracted"
    )
    assert ok is False
    assert reason == "aggregator_artifact_archive_unsafe_entry"
    assert not (tmp_path / "escape.txt").exists()


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
    assert "actions/artifacts/" in script
    assert "aggregator_artifact_digest_verified" in script
    assert "updatedAt" in script
    assert "classify" in script
    assert "pending" in script
    assert "MAX_ARTIFACT_ARCHIVE_BYTES" in script
    assert "selectors.DefaultSelector" in script
    assert "is_allowed_dispatch" in script
    assert "reject-non-main-manual-dispatch" in workflow



def test_workflow_finalizes_a_lifecycle_report_even_when_preflight_fails():
    workflow = (
        ROOT / ".github" / "workflows" / "ola-24x7-watchdog.yml"
    ).read_text(encoding="utf-8")

    assert "Initialize watchdog lifecycle evidence" in workflow
    assert "Finalize watchdog lifecycle evidence" in workflow
    assert 'report["run.end"]' in workflow


def embedded_python_blocks(source: str) -> list[str]:
    lines = source.splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == "python - <<'PY'":
            body = []
            index += 1
            while index < len(lines) and lines[index].strip() != "PY":
                body.append(lines[index])
                index += 1
            assert index < len(lines), "unterminated embedded Python block"
            blocks.append(textwrap.dedent("\n".join(body)))
        index += 1
    return blocks


def test_watchdog_embedded_python_is_syntactically_valid():
    workflow = (
        ROOT / ".github" / "workflows" / "ola-24x7-watchdog.yml"
    ).read_text(encoding="utf-8")
    blocks = embedded_python_blocks(workflow)

    assert len(blocks) == 3
    for index, block in enumerate(blocks):
        compile(block, f"ola-24x7-watchdog::<embedded-{index}>", "exec")


def test_watchdog_finalizer_writes_valid_terminal_lifecycle_report(tmp_path):
    workflow = (
        ROOT / ".github" / "workflows" / "ola-24x7-watchdog.yml"
    ).read_text(encoding="utf-8")
    finalizer = embedded_python_blocks(workflow)[1]
    initial = {
        "schema": "ola-24x7-watchdog-evidence-v1",
        "run.start": "2026-11-17T08:00:00Z",
        "run.end": None,
        "source_sha": SOURCE_SHA,
        "decision": "UNKNOWN",
        "action": "NONE",
        "reason": "watchdog_preflight_not_completed",
    }
    (tmp_path / "watchdog-evidence.json").write_text(
        json.dumps(initial), encoding="utf-8"
    )

    subprocess.run([sys.executable, "-c", finalizer], cwd=tmp_path, check=True)
    result = json.loads(
        (tmp_path / "watchdog-evidence.json").read_text(encoding="utf-8")
    )

    assert result["run.start"] == initial["run.start"]
    assert result["run.end"]
    assert result["decision"] == "STOP"
    assert result["reason"] == "watchdog_preflight_failed"



def test_pending_exact_sha_flow_is_waited_not_blocked():
    result = choose_flow_action(
        [flow_run(status="pending", conclusion="")],
        SOURCE_SHA,
    )

    assert result["action"] == "WAIT"
    assert result["reason"] == "active_main_flow"


def test_artifact_download_aborts_before_writing_beyond_declared_size(tmp_path, monkeypatch):
    from scripts.ola_watchdog import download_and_verify_artifact_archive

    install_fake_gh(tmp_path, monkeypatch, b"x" * (1024 * 1024))
    destination = tmp_path / "extracted"
    ok, reason = download_and_verify_artifact_archive(
        "example/OLA",
        42,
        "sha256:" + ("0" * 64),
        128,
        destination,
    )

    assert ok is False
    assert reason == "aggregator_artifact_archive_size_mismatch"
    partial_archive = tmp_path / "ola-auto-evidence-artifact.zip"
    assert not partial_archive.exists() or partial_archive.stat().st_size <= 128


def test_manual_watchdog_dispatch_is_restricted_to_main_ref():
    workflow = (
        ROOT / ".github" / "workflows" / "ola-24x7-watchdog.yml"
    ).read_text(encoding="utf-8")

    assert "if: github.event_name != 'workflow_dispatch' || github.ref == 'refs/heads/main'" in workflow
    assert "if: github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'" in workflow


def test_manual_dispatch_from_non_main_is_blocked_before_git_or_github(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature/untrusted")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    def forbidden_command(*args, **kwargs):
        raise AssertionError("non-main manual dispatch must not call git or GitHub")

    monkeypatch.setattr("scripts.ola_watchdog.subprocess.run", forbidden_command)

    report = run_watchdog()

    assert report["decision"] == "HUMAN_GATE"
    assert report["action"] == "NONE"
    assert report["reason"] == "manual_dispatch_ref_not_main"
    persisted = json.loads((tmp_path / "watchdog-evidence.json").read_text(encoding="utf-8"))
    assert persisted["run.start"]
    assert persisted["run.end"]
    assert persisted["source_sha"] is None
