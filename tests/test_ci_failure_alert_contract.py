"""Security contracts for out-of-band CI failure notifications."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_WORKFLOW_IDENTITIES = {
    "Python package CI": ("396626525", ".github/workflows/python-package-conda.yml"),
    "OLA FINAL PRODUCTION GATE": ("371357685", ".github/workflows/final-production-gate.yml"),
    "Evidence Cryptography V4 Contract": ("420904854", ".github/workflows/evidence-cryptography-v4.yml"),
    "OLA Supply Chain Evidence Gate": ("372525275", ".github/workflows/supply-chain-evidence.yml"),
    "OLA 12h Autonomous Evidence Flow": ("364887427", ".github/workflows/ola-12h-autoflow.yml"),
    "OLA 24x7 Watchdog": ("365831610", ".github/workflows/ola-24x7-watchdog.yml"),
    "Real LLM Ollama Runtime Gate": ("369544728", ".github/workflows/ollama-real-runtime.yml"),
    "OLA E2E Gate": ("357357114", ".github/workflows/e2e.yml"),
    "OLA Local Staging Rehearsal": ("405088306", ".github/workflows/staging-rehearsal.yml"),
    "Provenance Mutation Gate": ("359127799", ".github/workflows/provenance-mutation.yml"),
    "OLA Real Runtime Stress Gate": ("371357688", ".github/workflows/runtime-stress.yml"),
    "OLA State Continuity and Stability": ("371357683", ".github/workflows/state-continuity.yml"),
    "OLA CodeQL": ("369195481", ".github/workflows/codeql.yml"),
    "OLA paid-order PostgreSQL contract": ("410079547", ".github/workflows/paid-order-postgres.yml"),
    "OLA DI-OS Product Gate": ("363759316", ".github/workflows/ola-product-gate.yml"),
    "OLA Decision Evidence Gate": ("365083925", ".github/workflows/decision-evidence-gate.yml"),
    "Provenance Gate Final": ("359332631", ".github/workflows/provenance-gate-final.yml"),
    "Nina Igor Gate": ("361712153", ".github/workflows/nina-igor-gate.yml"),
    "Nina TDD": ("361710932", ".github/workflows/nina-tdd.yml"),
    "NINA Parallel DAG Gate": ("387920095", ".github/workflows/nina-parallel-dag.yml"),
    "Evidence Graph v0.1": ("369517905", ".github/workflows/evidence-graph.yml"),
    "Revenue Surface Gate": ("362005656", ".github/workflows/revenue-surface.yml"),
    "Nina Real Runtime Provenance Gate (OpenAI optional)": ("361725608", ".github/workflows/nina-real-runtime-provenance.yml"),
    "OLA Frontier Baseline": ("365085238", ".github/workflows/frontier-baseline.yml"),
}


class CIFailureAlertContractTests(unittest.TestCase):
    def test_pr_capable_python_ci_has_no_issue_write_token(self):
        workflow = (ROOT / ".github/workflows/python-package-conda.yml").read_text(encoding="utf-8")
        self.assertNotIn("  notify-failure:", workflow)
        self.assertNotIn("issues: write", workflow)

    def test_notifier_runs_after_failed_or_cancelled_workflows(self):
        workflow = (ROOT / ".github/workflows/ci-failure-notifier.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        self.assertIn('"Python package CI"', workflow)
        self.assertIn('"OLA FINAL PRODUCTION GATE"', workflow)
        self.assertIn("    types:\n      - completed", workflow)
        self.assertIn("github.event.workflow_run.conclusion != 'success'", workflow)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", workflow)
        self.assertIn("zizmor: ignore[dangerous-triggers]", workflow)
        self.assertIn("expected_workflow_id=\"396626525\"", workflow)
        self.assertIn("expected_workflow_id=\"371357685\"", workflow)
        self.assertIn("expected_workflow_path=", workflow)

    def test_notifier_has_minimal_permissions_and_never_executes_pr_artifacts(self):
        workflow = (ROOT / ".github/workflows/ci-failure-notifier.yml").read_text(encoding="utf-8")
        self.assertIn("permissions: {}", workflow)
        self.assertIn("      actions: read", workflow)
        self.assertIn("      issues: write", workflow)
        self.assertNotIn("actions/checkout@", workflow)
        self.assertNotIn("actions/download-artifact@", workflow)
        self.assertNotIn("docker build", workflow)
        self.assertNotIn("pytest", workflow)

    def test_incident_contains_exact_run_and_conclusion_and_is_deduplicated(self):
        workflow = (ROOT / ".github/workflows/ci-failure-notifier.yml").read_text(encoding="utf-8")
        for contract in (
            "gh api",
            "gh issue list",
            "gh issue create",
            "gh issue comment",
            "gh issue view",
            "SOURCE_SHA:",
            "RUN_ID:",
            "RUN_ATTEMPT:",
            "RUN_URL:",
            "RUN_CONCLUSION:",
            "RUN_EVENT:",
            "actual_workflow_id",
            "actual_workflow_path",
            "actual_head_repository",
            "actions/runs/$RUN_ID/jobs?per_page=100",
            "CI_INCIDENT=RECORDED",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, workflow)

    def test_scorecard_oidc_is_main_ref_only(self):
        workflow = (ROOT / ".github/workflows/supply-chain-evidence.yml").read_text(encoding="utf-8")
        scorecard = workflow.split("  scorecard:", 1)[1].split("\n  zizmor:", 1)[0]
        self.assertIn("github.ref == 'refs/heads/main'", scorecard)
        self.assertIn("github.event_name != 'pull_request'", scorecard)
        self.assertIn("id-token: write", scorecard)

    def test_final_gate_does_not_keep_a_second_in_band_issue_writer(self):
        workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertNotIn("  notify-release-failure:", workflow)
        self.assertNotIn("issues: write", workflow)


    def test_notifier_covers_all_required_release_and_liveness_workflows(self):
        workflow = (ROOT / ".github/workflows/ci-failure-notifier.yml").read_text(encoding="utf-8")
        lines = workflow.splitlines()
        start = lines.index("    workflows:")
        end = lines.index("    types:", start)
        workflow_list = "\n".join(lines[start + 1:end])
        self.assertEqual(len(EXPECTED_WORKFLOW_IDENTITIES), workflow_list.count('      - "'))
        self.assertEqual(len(EXPECTED_WORKFLOW_IDENTITIES), workflow.count("expected_workflow_id="))
        for name, (workflow_id, workflow_path) in EXPECTED_WORKFLOW_IDENTITIES.items():
            with self.subTest(workflow=name):
                self.assertIn(f'      - "{name}"', workflow_list)
                self.assertIn(f'expected_workflow_id="{workflow_id}"', workflow)
                self.assertIn(f'expected_workflow_path="{workflow_path}"', workflow)
        self.assertIn('"OLA 12h Autonomous Evidence Flow"', workflow_list)
        self.assertIn('"OLA 24x7 Watchdog"', workflow_list)
        self.assertIn('"OLA Frontier Baseline"', workflow_list)
if __name__ == "__main__":
    unittest.main()
