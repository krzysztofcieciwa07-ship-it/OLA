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


    def test_runtime_gate_producers_bind_to_exact_pr_source(self):
        # Regression: pull_request default checkout/github.sha can be a
        # synthetic merge commit rather than the reviewed PR head.
        producers = (
            ".github/workflows/e2e.yml",
            ".github/workflows/provenance-gate-final.yml",
            ".github/workflows/provenance-mutation.yml",
        )
        for filename in producers:
            with self.subTest(workflow=filename):
                content = (ROOT / filename).read_text(encoding="utf-8")
                lines = content.splitlines()
                self.assertIn("EXPECTED_SOURCE_SHA: " + SOURCE, content)
                self.assertIn("OLA_API_KEY_PEPPER: " + SOURCE, content)
                checkouts = [
                    index for index, line in enumerate(lines)
                    if "uses: actions/checkout@" in line
                ]
                self.assertGreater(len(checkouts), 0)
                for index in checkouts:
                    block = "\n".join(lines[index + 1:index + 9])
                    self.assertIn("ref: " + SOURCE, block)
                    self.assertIn("persist-credentials: false", block)
                self.assertIn('actual="$(git rev-parse HEAD)"', content)
                self.assertIn('if [ "$actual" != "$EXPECTED_SOURCE_SHA" ]; then', content)
                self.assertIn('echo "::error::Source checkout mismatch:', content)
                self.assertIn("exit 1", content)
                self.assertIn("EXACT_SOURCE_SHA_VERIFIED=$actual", content)
                self.assertIn("docker build --tag ola:${EXPECTED_SOURCE_SHA} .", content)
                self.assertIn('OLA_RUNTIME_COMMIT="${EXPECTED_SOURCE_SHA}"', content)
                self.assertIn("EXPECTED_COMMIT: " + SOURCE, content)
                self.assertNotIn("${GITHUB_SHA}", content)
                self.assertNotIn("EXPECTED_COMMIT: ${{ github.sha }}", content)

        e2e = (ROOT / producers[0]).read_text(encoding="utf-8")
        self.assertIn("name: ola-runtime-e2e-" + SOURCE, e2e)
        self.assertIn('"commit=${EXPECTED_SOURCE_SHA}"', e2e)

    def test_release_manifest_never_calls_green_ci_production_verified(self):
        content = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn('status="ATTESTED_PENDING_HUMAN"', content)
        self.assertNotIn('status="VERIFIED"', content)
        self.assertIn('python -m unittest discover -s tests -p "test_release_source_binding.py"', content)


    def test_automated_runtime_never_claims_human_approval(self):
        proof = (ROOT / ".github/workflows/nina-real-runtime-provenance.yml").read_text(encoding="utf-8")
        igor = (ROOT / ".github/workflows/igor-independent-evidence.yml").read_text(encoding="utf-8")
        self.assertIn('"human_gate":"PENDING"', proof)
        self.assertNotIn('"human_gate":"VERIFIED"', proof)
        self.assertIn('assert d["human_gate"]=="PENDING"', proof)
        self.assertIn('assert record_hash==hashlib.sha256(', proof)
        self.assertNotIn('assert record_hash==api_key_fingerprint(', proof)
        self.assertIn('assert d["human_gate"]=="PENDING"', igor)


if __name__ == "__main__":
    unittest.main()
