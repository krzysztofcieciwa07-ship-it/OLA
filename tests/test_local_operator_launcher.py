"""Local operator launcher fails closed before touching Docker or secrets."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/local_operator_demo.py"


def test_launcher_lists_manual_lifecycle_without_starting_a_service(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    run = subprocess.run([sys.executable, str(LAUNCHER), "--help"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert "{up,status,down}" in run.stdout
    assert not (tmp_path / ".ola-dios-local").exists()


def test_launcher_status_refuses_unknown_demo_without_creating_any_state(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    run = subprocess.run([sys.executable, str(LAUNCHER), "status"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
    assert run.returncode != 0
    assert "BLOCKED" in run.stderr
    assert not (tmp_path / ".ola-dios-local").exists()


def test_launcher_never_contains_production_keys_or_storage(monkeypatch):
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'secrets.token_urlsafe(36)' in source
    assert 'secrets.token_hex(32)' in source
    assert 'os.O_EXCL' in source
    assert 'os.fchmod(stream.fileno(), 0o600)' in source
    assert '"--volumes"' in source
    assert "0.0.0.0" not in source
