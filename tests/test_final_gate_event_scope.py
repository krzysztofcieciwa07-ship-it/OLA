"""Regression tests for exact-source release gate event scoping."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FinalGateEventScopeTests(unittest.TestCase):
    def test_main_push_lookup_is_scoped_to_main_branch(self):
        workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn('pull_request) event_filter="&event=pull_request" ;;', workflow)
        self.assertIn('push) event_filter="&event=push&branch=main" ;;', workflow)
        self.assertIn('workflow_dispatch) event_filter="&branch=${GITHUB_REF_NAME}" ;;', workflow)
        self.assertNotIn('pull_request|push)', workflow)

    def test_candidate_runs_are_bound_to_sha_event_and_pr_identity(self):
        workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        for contract in (
            'TARGET_SOURCE_SHA: ${{ steps.target.outputs.sha }}',
            'PR_NUMBER: ${{ github.event.pull_request.number || 0 }}',
            'run.get("head_sha") != target_sha',
            'run.get("head_branch") == "main"',
            'run.get("event") != "pull_request"',
            'associated_pr.get("number")',
            'base.get("ref") == "main"',
            'run.get("path") != expected_path',
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, workflow)

    def test_local_staging_rehearsal_runs_on_main_push_and_pr(self):
        workflow = (ROOT / ".github/workflows/staging-rehearsal.yml").read_text(encoding="utf-8")
        trigger_block = workflow.split("permissions:", 1)[0]
        self.assertIn("  push:\n    branches:\n      - main", trigger_block)
        self.assertIn("  pull_request:", trigger_block)
        self.assertIn("  workflow_dispatch:", trigger_block)


if __name__ == "__main__":
    unittest.main()
