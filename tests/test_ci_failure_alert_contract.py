"""Security contracts for out-of-band CI failure notifications."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


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
            "gh run view",
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


if __name__ == "__main__":
    unittest.main()
