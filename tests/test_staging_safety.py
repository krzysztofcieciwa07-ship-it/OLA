"""Negative operational tests: dirty build source and failing Docker teardown."""
import json
from types import SimpleNamespace

from scripts import staging_rehearsal as stage


def test_dirty_checkout_blocks_before_container_build(monkeypatch, capsys):
    sha = "a" * 40
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", sha)
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "0123456789abcdef0123456789abcdef")
    commands = []

    def fake_run(*args, **kwargs):
        commands.append(args)
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return sha
        if args[:2] == ("git", "status"):
            return " M app/main.py"
        if args[0] == "docker":
            raise RuntimeError("Docker reached with dirty source")
        return ""

    monkeypatch.setattr(stage, "run", fake_run)
    monkeypatch.setattr(stage.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    assert stage.main() == 1
    assert not any(cmd[0] == "docker" for cmd in commands)
    assert "dirty" in capsys.readouterr().err.lower()


def test_teardown_failure_invalidates_receipt_and_return_code(monkeypatch, tmp_path):
    sha = "b" * 40
    monkeypatch.setenv("OLA_RUNTIME_COMMIT", sha)
    monkeypatch.setenv("OLA_API_KEY_PEPPER", "0123456789abcdef0123456789abcdef")
    proof = tmp_path / "staging-proof.json"
    monkeypatch.setattr(stage, "PROOF", proof)
    monkeypatch.setattr(stage, "await_ready", lambda **kwargs: None)
    monkeypatch.setattr(stage.time, "sleep", lambda _: None)

    def fake_run(*args, **kwargs):
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return sha
        if args[:2] == ("git", "status"):
            return ""
        if args[0] == "docker" and "staging_verify.py" in args:
            return json.dumps({
                "status": "VERIFIED", "tamper_blocked": True,
                "chain_root": "e" * 64,
            })
        return ""

    def fake_http(path, payload=None, key=None):
        if path == "/readyz":
            return 200, {"core_status": "READY", "system_acceptance": "NOT_VERIFIED"}
        if path == "/audit" and key is None:
            return 401, {}
        if path == "/audit" and key == "wrong-key":
            return 401, {}
        return 200, {"status": "VERIFIED", "evidence_count": 5}

    monkeypatch.setattr(stage, "run", fake_run)
    monkeypatch.setattr(stage, "http", fake_http)
    monkeypatch.setattr(stage.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    assert stage.main() == 1
    assert not proof.exists(), "failed teardown must not leave a PASS receipt"
