"""Fail-closed release-source contract for all mandatory scan producers."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "${{ github.event.pull_request.head.sha || github.sha }}"


class ReleaseSourceBindingTest(unittest.TestCase):
    def test_security_checkout_uses_exact_source_sha(self):
        for filename in (
            ".github/workflows/codeql.yml",
            ".github/workflows/supply-chain-evidence.yml",
        ):
            with self.subTest(workflow=filename):
                lines = (ROOT / filename).read_text(encoding="utf-8").splitlines()
                count = 0
                for index, line in enumerate(lines):
                    if "uses: actions/checkout@" not in line:
                        continue
                    count += 1
                    block = "\n".join(lines[index + 1:index + 9])
                    self.assertIn("ref: " + SOURCE, block)
                    self.assertIn("persist-credentials: false", block)
                self.assertGreater(count, 0)

    def test_scan_producers_check_actual_git_head(self):
        for filename in (
            ".github/workflows/codeql.yml",
            ".github/workflows/supply-chain-evidence.yml",
        ):
            with self.subTest(workflow=filename):
                content = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn('EXPECTED_SOURCE_SHA: ' + SOURCE, content)
                self.assertIn('git rev-parse HEAD', content)
                self.assertIn('if [ "$checked_out" != "$EXPECTED_SOURCE_SHA" ]; then', content)
                self.assertIn('exit 1', content)

    def test_release_manifest_never_calls_green_ci_production_verified(self):
        content = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn('status="ATTESTED_PENDING_HUMAN"', content)
        self.assertNotIn('status="VERIFIED"', content)
        self.assertIn('python -m unittest discover -s tests -p "test_release_source_binding.py"', content)


if __name__ == "__main__":
    unittest.main()
