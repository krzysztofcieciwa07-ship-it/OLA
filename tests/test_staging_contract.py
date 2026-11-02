"""Safety contracts for the OLA localhost-only staging rehearsal."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_staging_manifest_binds_loopback_and_persists_evidence():
    text = (ROOT / 'deploy/staging/compose.yaml').read_text()
    assert '127.0.0.1:18080:8000' in text
    assert 'ola-staging-data:/data' in text
    assert 'read_only: true' in text
    assert 'no-new-privileges:true' in text
    assert 'OLA_API_KEY_PEPPER: "${OLA_API_KEY_PEPPER:?required}"' in text
    assert 'OLA_RUNTIME_COMMIT: "${OLA_RUNTIME_COMMIT:?required}"' in text


def test_staging_smoke_checks_restart_and_tamper():
    script = (ROOT / 'scripts/staging_rehearsal.py').read_text()
    for contract in ('/health', '/audit', 'restart', '--tamper-check', '401', 'scripts/staging_verify.py'):
        assert contract in script
    verifier = (ROOT / 'scripts/staging_verify.py').read_text()
    assert 'def verify_chain(' in verifier


def test_staging_ci_uses_temporary_secret_and_uploads_receipt():
    workflow = (ROOT / '.github/workflows/staging-rehearsal.yml').read_text()
    assert 'permissions:\n  contents: read' in workflow
    assert 'persist-credentials: false' in workflow
    assert 'secrets.token_hex(32)' in workflow
    assert 'scripts/staging_rehearsal.py' in workflow
    assert 'staging-proof.json' in workflow
