import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_release_gates import (IGOR_JOB_NAME, REQUIRED_EXACT, REFERENCE_GATES, ReleaseGateError, _verify_source_branch_head, evaluate_release_gates)

SHA = "a" * 40


def run(name, *, status="completed", conclusion="success", sha=SHA, run_id=1, created="2026-11-12T14:00:00Z"):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": sha,
            "id": run_id, "created_at": created}


def passing_snapshot():
    exact = [run(name, run_id=i + 1) for i, name in enumerate(REQUIRED_EXACT)]
    reference = [run(name, sha="b" * 40, run_id=100 + i) for i, name in enumerate(REFERENCE_GATES)]
    jobs = [{"name": IGOR_JOB_NAME, "status": "completed", "conclusion": "success", "id": 900}]
    return exact, reference, jobs


class ReleaseGatePolicyTests(unittest.TestCase):
    def test_verifies_all_exact_source_gates_and_independent_igor(self):
        exact, reference, jobs = passing_snapshot()
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["pending"], {})
        self.assertEqual(result["failed"], {})

    def test_missing_required_gate_is_pending_not_success(self):
        exact, reference, jobs = passing_snapshot()
        exact = [item for item in exact if item["name"] != REQUIRED_EXACT[0]]
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertIn(REQUIRED_EXACT[0], result["missing"])

    def test_in_progress_required_gate_is_pending(self):
        exact, reference, jobs = passing_snapshot()
        exact[0] = run(REQUIRED_EXACT[0], status="in_progress", conclusion=None)
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertIn(REQUIRED_EXACT[0], result["pending"])

    def test_failed_required_gate_blocks(self):
        exact, reference, jobs = passing_snapshot()
        exact[0] = run(REQUIRED_EXACT[0], conclusion="failure")
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn(REQUIRED_EXACT[0], result["failed"])

    def test_wrong_source_sha_blocks(self):
        exact, reference, jobs = passing_snapshot()
        exact[0] = run(REQUIRED_EXACT[0], sha="c" * 40)
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["failed"][REQUIRED_EXACT[0]]["reason"], "source_sha_mismatch")

    def test_independent_igor_missing_is_pending(self):
        exact, reference, _ = passing_snapshot()
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=[])
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("IGOR Independent Ollama Evidence Gate", result["pending"])

    def test_independent_igor_skipped_or_failed_blocks(self):
        exact, reference, jobs = passing_snapshot()
        jobs[0]["conclusion"] = "skipped"
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "BLOCKED")

    def test_missing_frontier_baseline_is_pending(self):
        exact, _, jobs = passing_snapshot()
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=[], igor_jobs=jobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("reference:OLA Frontier Baseline", result["missing"])

    @patch("verify_release_gates._get_json")
    def test_current_source_branch_head_is_accepted(self, get_json):
        get_json.return_value = {"commit": {"sha": SHA}}
        _verify_source_branch_head(
            base="https://api.github.com/repos/example/OLA",
            source_ref="refs/heads/security/oci-release-chain-20261112",
            expected_sha=SHA,
            token="token",
        )
        get_json.assert_called_once_with(
            "https://api.github.com/repos/example/OLA/branches/security%2Foci-release-chain-20261112",
            "token",
        )

    @patch("verify_release_gates._get_json")
    def test_moved_source_branch_blocks_release(self, get_json):
        get_json.return_value = {"commit": {"sha": "c" * 40}}
        with self.assertRaises(ReleaseGateError):
            _verify_source_branch_head(
                base="https://api.github.com/repos/example/OLA",
                source_ref="refs/heads/security/oci-release-chain-20261112",
                expected_sha=SHA,
                token="token",
            )

    def test_non_branch_source_ref_is_rejected(self):
        with self.assertRaises(ValueError):
            _verify_source_branch_head(
                base="https://api.github.com/repos/example/OLA",
                source_ref="refs/tags/v1.0.0",
                expected_sha=SHA,
                token="token",
            )

    def test_newest_duplicate_run_wins(self):
        exact, reference, jobs = passing_snapshot()
        exact.append(run(REQUIRED_EXACT[0], conclusion="failure", run_id=999, created="2026-11-12T15:00:00Z"))
        result = evaluate_release_gates(expected_sha=SHA, exact_runs=exact, reference_runs=reference, igor_jobs=jobs)
        self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
