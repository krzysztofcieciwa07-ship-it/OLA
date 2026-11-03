"""Staging deployment guardrails: static contract and run/proof requirements."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_listener_and_volume_are_required():
    config = (ROOT / "deploy/staging/compose.yaml").read_text()
    assert '127.0.0.1:18080:8000' in config
    assert 'ola-staging-data:/data' in config
    assert 'read_only: true' in config
    assert 'no-new-privileges:true' in config
    assert 'OLA_API_KEY_PEPPER:' in config
    assert 'OLA_RUNTIME_COMMIT:' in config


def test_rehearsal_is_a_real_restart_and_negative_test():
    script = (ROOT / "scripts/staging_rehearsal.py").read_text()
    for contract in ('/readyz', '/audit', 'restart', '--tamper-check', '401',
                     'scripts/staging_verify.py', 'health_stable_12s'):
        assert contract in script


def test_staging_workflow_runs_unprivileged_with_exact_checkout():
    ci = (ROOT / ".github/workflows/staging-rehearsal.yml").read_text()
    assert 'permissions:\n  contents: read' in ci
    assert 'persist-credentials: false' in ci
    assert 'secrets.token_hex(32)' in ci
    assert 'scripts/staging_rehearsal.py' in ci
    assert 'staging-proof.json' in ci
