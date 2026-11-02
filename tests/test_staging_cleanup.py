"""Safety tests: a passing staging run may only be published after cleanup."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import staging_rehearsal as sr

SOURCE_SHA = "a" * 40


@pytest.fixture
def simulate_successful_checks(monkeypatch, tmp_path):
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", SOURCE_SHA)
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "ci-fixture-only-" + "x" * 64)
    proof = tmp_path / "staging-proof.json"
    monkeypatch.setattr(sr, "PROOF", proof)
    monkeypatch.setattr(sr.time, "sleep", lambda _: None)

    def fake_run(*args, input_text=None):
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return SOURCE_SHA
        if "scripts/staging_verify.py" in args:
            return json.dumps({"status": "VERIFIED", "tamper_blocked": "--tamper-check" in args,
                               "chain_root": "c" * 64})
        return ""
    monkeypatch.setattr(sr, "run", fake_run)
    monkeypatch.setattr(sr, "await_health", lambda: None)

    def fake_http(path, payload=None, key=None):
        if path == "/health":
            return 200, {"status": "ok"}
        if path == "/audit" and (key is None or key == "wrong-key"):
            return 401, {"detail": "invalid API key"}
        return 200, {"status": "VERIFIED", "evidence_count": 5}
    monkeypatch.setattr(sr, "http", fake_http)
    return proof


def test_cleanup_error_blocks_release_and_prevents_pass_receipt(monkeypatch, simulate_successful_checks, capsys):
    monkeypatch.setattr(sr.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    assert sr.main() != 0, "failed resource teardown must block staging release"
    assert not simulate_successful_checks.exists(), "failed cleanup must not leave PASS artifact"
    assert "BLOCKED" in capsys.readouterr().err


def test_success_receipt_is_written_only_after_successful_teardown(monkeypatch, simulate_successful_checks):
    cleanup_seen = []

    def teardown(*args, **kwargs):
        assert not simulate_successful_checks.exists(), "PASS receipt must not predate resource cleanup"
        cleanup_seen.append(True)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(sr.subprocess, "run", teardown)
    assert sr.main() == 0
    assert cleanup_seen
    receipt = json.loads(simulate_successful_checks.read_text())
    assert receipt["status"] == "PASS"
    assert "cleanup_verified" in receipt["checks"]
