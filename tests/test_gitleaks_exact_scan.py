"""Regression tests for exact-SHA Gitleaks scanning."""
import unittest
from pathlib import Path

from scripts.gitleaks_exact_scan import build_scan_plan

ROOT = Path(__file__).resolve().parents[1]


class GitleaksExactSourceTests(unittest.TestCase):
    def setUp(self):
        self.target = "9f83912182cea5e9a3d6292d0e1c6632048a64be"
        self.base = "8adf30cd5e41a18a5345f66e67f5ddcdbc164862"
        self.merge_base = "28c3f4ccc1b584a9274500ad77ad87366d318f41"
        self.stale_api_head = "3eeeec4d5da6afaed38861fc6228a34d3b4f8dbd"

    def test_pr_range_ends_at_immutable_event_sha_not_stale_api_head(self):
        plan = build_scan_plan(
            "pull_request", self.target, base_sha=self.base, merge_base=self.merge_base
        )
        self.assertEqual(self.target, plan["source_sha"])
        self.assertEqual(f"{self.merge_base}..{self.target}", plan["scan_range"])
        self.assertEqual(
            f"--no-merges --first-parent {self.merge_base}..{self.target}",
            plan["log_opts"],
        )
        self.assertNotIn(self.stale_api_head, plan["log_opts"])

    def test_push_range_uses_exact_before_and_after(self):
        before = "c" * 40
        plan = build_scan_plan("push", self.target, before_sha=before)
        self.assertEqual(f"{before}..{self.target}", plan["scan_range"])
        self.assertIn(self.target, plan["log_opts"])

    def test_first_push_and_manual_runs_scan_full_history(self):
        zero = "0" * 40
        self.assertEqual("FULL_HISTORY", build_scan_plan("push", self.target, before_sha=zero)["scan_range"])
        self.assertEqual("FULL_HISTORY", build_scan_plan("workflow_dispatch", self.target)["scan_range"])
        self.assertEqual("FULL_HISTORY", build_scan_plan("schedule", self.target)["scan_range"])

    def test_no_change_scans_the_exact_target_commit(self):
        self.assertEqual(self.target, build_scan_plan("push", self.target, before_sha=self.target)["scan_range"])
        self.assertEqual(
            self.target,
            build_scan_plan("pull_request", self.target, base_sha=self.base, merge_base=self.target)["scan_range"],
        )

    def test_rejects_invalid_sha_inputs(self):
        with self.assertRaises(ValueError):
            build_scan_plan("pull_request", self.target, base_sha="bad", merge_base=self.merge_base)
        with self.assertRaises(ValueError):
            build_scan_plan("pull_request", self.target, base_sha=self.base, merge_base="bad")
        with self.assertRaises(ValueError):
            build_scan_plan("push", self.target, before_sha="bad")

    def test_workflow_uses_explicit_exact_source_scan(self):
        content = (ROOT / ".github/workflows/supply-chain-evidence.yml").read_text(encoding="utf-8")
        self.assertIn("continue-on-error: true", content)
        self.assertIn('GITLEAKS_ENABLE_UPLOAD_ARTIFACT: "false"', content)
        self.assertIn('GITLEAKS_VERSION: "8.24.3"', content)
        self.assertIn("python scripts/gitleaks_exact_scan.py", content)
        self.assertIn("gitleaks-exact-scan.json", content)
        self.assertIn("gitleaks-exact-source-results.sarif", content)


if __name__ == "__main__":
    unittest.main()
