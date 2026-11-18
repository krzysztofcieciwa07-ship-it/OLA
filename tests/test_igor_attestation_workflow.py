from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_final_gate_generates_main_only_sigstore_attestation_for_igor_bundle():
    workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
    attestor = workflow.split("  attest-production:\n", 1)[1]

    assert "artifact-metadata: write" in attestor
    assert "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6" in attestor
    assert "igor-ollama-evidence-bundle.tar.gz" in attestor
    assert "predicate-type:" in attestor
    assert "python scripts/igor_attestation.py prepare" in attestor
    assert "python scripts/igor_attestation.py verify" in attestor
    assert "gh attestation verify" in attestor


def test_final_manifest_cannot_claim_attested_without_verified_igor_bundle():
    workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
    assert "IGOR_ATTESTATION_STATUS" in workflow
    assert '"igor_bundle_attestation"' in workflow
    assert "ATTESTED_PENDING_HUMAN" in workflow
