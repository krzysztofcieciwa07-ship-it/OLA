
"""Staging controls: exact source, isolated listener, restore and health window."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_listener_volume_and_build_source_are_required():
    config = (ROOT / "deploy/staging/compose.yaml").read_text()
    assert "127.0.0.1:18080:8000" in config
    assert "ola-staging-data:/data" in config
    assert "read_only: true" in config
    assert "no-new-privileges:true" in config
    assert "OLA_API_KEY_PEPPER:" in config
    assert "OLA_REQUIRE_BUILD_INFO: \"1\"" in config
    assert "OLA_SOURCE_COMMIT:" in config
    assert "0000000000000000000000000000000000000000" in config


def test_rehearsal_covers_restart_restore_tamper_and_stability():
    script = (ROOT / "scripts/staging_rehearsal.py").read_text()
    for contract in ("/readyz", "/audit", "restart", "--tamper-check",
                     "health_stable_12s", "BACKUP_RESTORE",
                     "PRAGMA integrity_check", "sqlite_backup_restore_verified"):
        assert contract in script


def test_staging_workflow_is_unprivileged_and_uses_exact_checkout():
    ci = (ROOT / ".github/workflows/staging-rehearsal.yml").read_text()
    assert "permissions:\n  contents: read" in ci
    assert "persist-credentials: false" in ci
    assert "secrets.token_hex(32)" in ci
    assert "scripts/staging_rehearsal.py" in ci
    assert "staging-proof.json" in ci
