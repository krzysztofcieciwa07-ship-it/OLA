"""Contract tests for independently attesting real Ollama evidence."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OllamaIndependentEvidenceContractTest(unittest.TestCase):
    def test_ollama_producer_exports_verifiable_tenant_database(self):
        workflow = (ROOT / ".github/workflows/nina-igor-ollama.yml").read_text(encoding="utf-8")
        self.assertIn("nina-ollama-evidence.sqlite3", workflow)
        self.assertIn("evidence_records", workflow)
        self.assertIn("nina-igor-ollama-full-flow-", workflow)
        self.assertIn("igor-independent-ollama-evidence.yml", workflow)

    def test_independent_gate_recomputes_real_ollama_evidence(self):
        workflow = (ROOT / ".github/workflows/igor-independent-ollama-evidence.yml").read_text(encoding="utf-8")
        for required in (
            "scripts/verify_agent_runtime.py",
            "--expected-provider",
            "ollama",
            "--expected-invocation-type",
            "real_llm",
            "--db-path",
            "nina-ollama-evidence.sqlite3",
            "TAMPER_MUTATION=BLOCK",
            "TAMPER_MUTATION=BLOCK",
            "HUMAN_GATE=PENDING",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)

    def test_pr_igor_chain_is_unprivileged_and_emits_unsigned_evidence(self):
        for filename in (
            ".github/workflows/ola-12h-autoflow.yml",
            ".github/workflows/nina-igor-ollama.yml",
            ".github/workflows/igor-independent-ollama-evidence.yml",
            ".github/workflows/nina-real-runtime-provenance.yml",
            ".github/workflows/igor-independent-evidence.yml",
        ):
            with self.subTest(workflow=filename):
                workflow = (ROOT / filename).read_text(encoding="utf-8")
                self.assertNotIn("id-token: write", workflow)
                self.assertNotIn("attestations: write", workflow)
                self.assertNotIn("actions/attest@", workflow)

    def test_igor_evidence_remains_bound_and_human_gated(self):
        workflow = (ROOT / ".github/workflows/igor-independent-ollama-evidence.yml").read_text(encoding="utf-8")
        self.assertIn("SOURCE_COMMIT: ${{ inputs.source_commit }}", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$SOURCE_COMMIT"', workflow)
        self.assertIn("TAMPER_MUTATION=BLOCK", workflow)
        self.assertIn('"human_gate":"PENDING"', workflow)
        self.assertIn("Human Gate hold", workflow)
        self.assertIn("Upload IGOR Ollama evidence", workflow)

    def test_human_gate_is_never_auto_approved(self):
        workflow = (ROOT / ".github/workflows/igor-independent-ollama-evidence.yml").read_text(encoding="utf-8")
        self.assertIn('"human_gate":"PENDING"', workflow)
        self.assertNotIn('"human_gate":"VERIFIED"', workflow)

    def test_final_production_requires_nested_independent_igor_job(self):
        workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn("OLA 12h Autonomous Evidence Flow", workflow)
        self.assertIn('autoflow_run = exact.get("OLA 12h Autonomous Evidence Flow")', workflow)
        self.assertIn("real_ollama_flow / nina-igor-ollama-full-flow", workflow)
        self.assertIn("real_ollama_flow / igor-independent-ollama / igor-ollama", workflow)
        self.assertIn("IGOR Independent Ollama Evidence Gate", workflow)
        self.assertIn("OLA 12h Evidence Aggregator", workflow)
        self.assertIn("jobs_by_name", workflow)


if __name__ == "__main__":
    unittest.main()
