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

    def test_required_evidence_producers_are_not_path_filtered(self):
        for filename in (
            ".github/workflows/evidence-cryptography-v4.yml",
            ".github/workflows/paid-order-postgres.yml",
        ):
            with self.subTest(workflow=filename):
                content = (ROOT / filename).read_text(encoding="utf-8")
                self.assertNotIn("    paths:", content)
                self.assertIn("  pull_request:", content)
                self.assertIn("  push:", content)


    def test_final_gate_oidc_permissions_are_confined_to_main_attestation_job(self):
        workflow = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        release_job = workflow.split("  final-production:", 1)[1].split("  attest-production:", 1)[0]
        self.assertNotIn("id-token: write", release_job)
        self.assertNotIn("attestations: write", release_job)
        self.assertIn("RELEASE_GATES_PASSED_PENDING_ATTESTATION", release_job)

        attest_job = workflow.split("  attest-production:", 1)[1]
        self.assertIn("github.event_name == 'push'", attest_job)
        self.assertIn("github.ref == 'refs/heads/main'", attest_job)
        self.assertIn("needs.final-production.result == 'success'", attest_job)
        self.assertIn("id-token: write", attest_job)
        self.assertIn("attestations: write", attest_job)
        self.assertIn("verify_supply_chain_attestation.py", attest_job)
        self.assertIn("actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093", attest_job)

    def test_local_staging_rehearsal_runs_on_main_push_and_pr(self):
        workflow = (ROOT / ".github/workflows/staging-rehearsal.yml").read_text(encoding="utf-8")
        trigger_block = workflow.split("permissions:", 1)[0]
        self.assertIn("  push:\n    branches:\n      - main", trigger_block)
        self.assertIn("  pull_request:", trigger_block)
        self.assertIn("  workflow_dispatch:", trigger_block)


if __name__ == "__main__":
    unittest.main()
