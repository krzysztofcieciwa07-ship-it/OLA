"""Contract tests for explicit CI failure notification and evidence."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CIFailureAlertContractTests(unittest.TestCase):
    def test_failure_alert_runs_after_the_test_job_fails(self):
        workflow = (ROOT / ".github/workflows/python-package-conda.yml").read_text(encoding="utf-8")
        self.assertIn("  notify-failure:", workflow)
        notify_job = workflow.split("  notify-failure:", 1)[1]
        self.assertIn("always()", notify_job)
        self.assertIn("needs.build-linux.result == 'failure'", notify_job)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", notify_job)
        self.assertIn("    needs: build-linux", notify_job)
        self.assertIn("      issues: write", notify_job)
        self.assertIn("      actions: read", notify_job)

    def test_python_failure_alert_skips_unwritable_fork_pull_requests(self):
        workflow = (ROOT / ".github/workflows/python-package-conda.yml").read_text(encoding="utf-8")
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", workflow)

    def test_main_release_gate_failure_creates_a_source_bound_incident(self):
        workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn("  notify-release-failure:", workflow)
        self.assertIn("needs.final-production.result == 'failure'", workflow)
        self.assertIn("github.event_name == 'push'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        for contract in (
            "issues: write",
            "gh run view",
            "gh issue list",
            "gh issue create",
            "gh issue comment",
            "gh issue view",
            "SOURCE_SHA:",
            "RUN_ID:",
            "RUN_ATTEMPT:",
            "RUN_URL:",
            "OLA_RELEASE_FAILURE_ALERT=RECORDED",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, workflow)

    def test_alert_is_deduplicated_and_contains_exact_run_identity(self):
        workflow = (ROOT / ".github/workflows/python-package-conda.yml").read_text(encoding="utf-8")
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
            "REPOSITORY_OWNER:",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, workflow)


if __name__ == "__main__":
    unittest.main()
