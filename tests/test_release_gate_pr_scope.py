"""Regression tests for exact PR identity binding in release evidence selection."""
from pathlib import Path
import unittest

from scripts.release_gate import (
    filter_expected_workflow_paths,
    filter_main_runs,
    filter_pull_request_runs,
)

ROOT = Path(__file__).resolve().parents[1]


class PullRequestEvidenceScopeTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.base_sha = "b" * 40
        self.match = {
            "id": 1,
            "event": "pull_request",
            "head_sha": self.sha,
            "head_branch": "feature/evidence",
            "pull_requests": [{
                "number": 253,
                "head": {"sha": self.sha, "ref": "feature/evidence"},
                "base": {"sha": self.base_sha, "ref": "main"},
            }],
        }

    def test_accepts_only_exact_pr_head_and_base(self):
        other_pr = {
            **self.match,
            "id": 2,
            "pull_requests": [{
                "number": 254,
                "head": {"sha": self.sha, "ref": "feature/evidence"},
                "base": {"sha": self.base_sha, "ref": "main"},
            }],
        }
        wrong_base_sha = {
            **self.match,
            "id": 3,
            "pull_requests": [{
                "number": 253,
                "head": {"sha": self.sha, "ref": "feature/evidence"},
                "base": {"sha": "c" * 40, "ref": "main"},
            }],
        }
        wrong_base_ref = {
            **self.match,
            "id": 4,
            "pull_requests": [{
                "number": 253,
                "head": {"sha": self.sha, "ref": "feature/evidence"},
                "base": {"sha": self.base_sha, "ref": "release"},
            }],
        }
        wrong_head = {**self.match, "id": 5, "head_sha": "d" * 40}
        wrong_branch = {**self.match, "id": 6, "head_branch": "other-branch"}
        wrong_event = {**self.match, "id": 7, "event": "push"}
        missing_association = {
            "id": 8,
            "event": "pull_request",
            "head_sha": self.sha,
            "head_branch": "feature/evidence",
        }

        selected = filter_pull_request_runs(
            [other_pr, wrong_base_sha, wrong_base_ref, wrong_head,
             wrong_branch, wrong_event, missing_association, self.match],
            pr_number=253,
            target_sha=self.sha,
            base_ref="main",
            base_sha=self.base_sha,
        )

        self.assertEqual([1], [run["id"] for run in selected])

    def test_fails_closed_for_invalid_pr_number(self):
        with self.assertRaises(ValueError):
            filter_pull_request_runs(
                [self.match], pr_number=0, target_sha=self.sha,
                base_ref="main", base_sha=self.base_sha,
            )

    def test_fails_closed_for_invalid_source_or_base_sha(self):
        for target_sha, base_sha in (("not-a-sha", self.base_sha), (self.sha, "not-a-sha")):
            with self.subTest(target_sha=target_sha, base_sha=base_sha):
                with self.assertRaises(ValueError):
                    filter_pull_request_runs(
                        [self.match], pr_number=253, target_sha=target_sha,
                        base_ref="main", base_sha=base_sha,
                    )

    def test_main_release_excludes_pull_request_and_other_branch_runs(self):
        main_push = {**self.match, "id": 10, "event": "push", "head_branch": "main"}
        main_dispatch = {**self.match, "id": 11, "event": "workflow_dispatch", "head_branch": "main"}
        main_schedule = {**self.match, "id": 12, "event": "schedule", "head_branch": "main"}
        pr_same_sha = {**self.match, "id": 13}
        other_branch = {**main_push, "id": 14, "head_branch": "release"}
        other_sha = {**main_push, "id": 15, "head_sha": "d" * 40}
        selected = filter_main_runs(
            [pr_same_sha, other_branch, other_sha, main_push, main_dispatch, main_schedule],
            target_sha=self.sha,
        )
        self.assertEqual([10, 11, 12], [run["id"] for run in selected])

    def test_main_release_rejects_pr_runs_on_main_branch_at_any_status(self):
        # A PR may have a head branch literally named "main". Its event identity,
        # not its branch label or run status, must keep it out of main evidence.
        pr_head_on_main = {
            **self.match,
            "head_branch": "main",
            "pull_requests": [{
                "number": 253,
                "head": {"sha": self.sha, "ref": "main"},
                "base": {"sha": self.base_sha, "ref": "main"},
            }],
        }
        pr_completed_success = {
            **pr_head_on_main,
            "id": 20,
            "status": "completed",
            "conclusion": "success",
        }
        pr_in_progress = {
            **pr_head_on_main,
            "id": 21,
            "status": "in_progress",
            "conclusion": None,
        }
        main_push = {
            **self.match,
            "id": 22,
            "event": "push",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }

        selected = filter_main_runs(
            [pr_completed_success, pr_in_progress, main_push],
            target_sha=self.sha,
        )

        self.assertEqual([22], [run["id"] for run in selected])

    def test_main_release_fails_closed_for_invalid_sha_or_event_allowlist(self):
        with self.assertRaises(ValueError):
            filter_main_runs([self.match], target_sha="not-a-sha")
        with self.assertRaises(ValueError):
            filter_main_runs([self.match], target_sha=self.sha, allowed_events={"pull_request"})

    def test_final_gate_passes_exact_pr_identity_to_selector(self):
        content = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn("TARGET_SOURCE_SHA: ${{ steps.target.outputs.sha }}", content)
        self.assertIn("PR_NUMBER: ${{ github.event.pull_request.number || 0 }}", content)
        self.assertIn("PR_BASE_SHA: ${{ github.event.pull_request.base.sha || '' }}", content)
        self.assertIn("filter_pull_request_runs(", content)
        self.assertIn("filter_main_runs(", content)
        self.assertIn('base_sha=os.environ.get("PR_BASE_SHA", "")', content)

    def test_pr_run_with_spoofed_workflow_name_is_rejected_by_path(self):
        """Reject display-name collisions from non-canonical workflow files."""
        malicious = {
            **self.match,
            "id": 20,
            "name": "Python package CI",
            "path": ".github/workflows/attacker.yml",
        }
        trusted = {
            **self.match,
            "id": 21,
            "name": "Python package CI",
            "path": ".github/workflows/python-package-conda.yml",
        }
        pr_scoped = filter_pull_request_runs(
            [malicious, trusted],
            pr_number=253,
            target_sha=self.sha,
            base_ref="main",
            base_sha=self.base_sha,
        )
        selected = filter_expected_workflow_paths(
            pr_scoped,
            {"Python package CI": ".github/workflows/python-package-conda.yml"},
        )
        self.assertEqual([21], [run["id"] for run in selected])

    def test_expected_workflow_path_filter_fails_closed_on_missing_path(self):
        missing_path = {**self.match, "name": "Python package CI"}
        selected = filter_expected_workflow_paths(
            [missing_path],
            {"Python package CI": ".github/workflows/python-package-conda.yml"},
        )
        self.assertEqual([], selected)

    def test_expected_workflow_path_filter_rejects_unsafe_or_duplicate_paths(self):
        with self.assertRaises(ValueError):
            filter_expected_workflow_paths(
                [self.match],
                {"Python package CI": "../attacker.yml"},
            )
        with self.assertRaises(ValueError):
            filter_expected_workflow_paths(
                [self.match],
                {
                    "Python package CI": ".github/workflows/shared.yml",
                    "OLA CodeQL": ".github/workflows/shared.yml",
                },
            )

    def test_final_gate_filters_expected_workflow_paths_before_name_selection(self):
        content = (ROOT / ".github" / "workflows" / "final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn("filter_expected_workflow_paths", content)
        self.assertIn('exact_data["workflow_runs"] = filter_expected_workflow_paths', content)
        self.assertIn('reference_data["workflow_runs"] = filter_expected_workflow_paths', content)


if __name__ == "__main__":
    unittest.main()
