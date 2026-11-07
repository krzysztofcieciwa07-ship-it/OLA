"""Fail-closed release-source contract for all mandatory scan producers."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "${{ github.event.pull_request.head.sha || github.sha }}"
RELEASE_SOURCE = "${{ github.sha }}"


class ReleaseSourceBindingTest(unittest.TestCase):
    def test_security_checkout_uses_exact_source_sha(self):
        for filename in (
            ".github/workflows/codeql.yml",
            ".github/workflows/supply-chain-evidence.yml",
        ):
            with self.subTest(workflow=filename):
                lines = (ROOT / filename).read_text(encoding="utf-8").splitlines()
                current_job = None
                count = 0
                for index, line in enumerate(lines):
                    if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
                        current_job = line.strip()[:-1]
                    if "uses: actions/checkout@" not in line:
                        continue
                    count += 1
                    block = "\n".join(lines[index + 1:index + 9])
                    self.assertIn("persist-credentials: false", block)
                    if filename.endswith("supply-chain-evidence.yml") and current_job == "oci-slsa-attestations":
                        self.assertIn("ref: " + RELEASE_SOURCE, block)
                        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', "\n".join(lines[index:index + 20]))
                    else:
                        self.assertIn("ref: " + SOURCE, block)
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

    def test_release_attestations_are_gated_and_feature_dispatch_is_rehearsal_only(self):
        content = (ROOT / ".github/workflows/supply-chain-evidence.yml").read_text(encoding="utf-8")
        self.assertIn("needs: [security-image, provenance-adapter-tests]", content)
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", content)
        self.assertIn("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/feat/oidc-human-gate-customer-bundle-20261107'", content)
        self.assertIn("attestations: write", content)
        self.assertIn("id-token: write", content)
        self.assertIn("Trivy scan exact image before publication", content)
        self.assertIn("Push exact scanned OCI image", content)
        self.assertIn("Verify registry digest against running container imageID", content)
        self.assertIn("docker pull \"$IMAGE_NAME@$OCI_DIGEST\"", content)
        self.assertIn("docker inspect --format '{{.Image}}' \"$container_name\"", content)
        self.assertIn('test "$container_image_id" = "$EXPECTED_IMAGE_ID"', content)
        self.assertIn('runtime-image-proof.json', content)
        self.assertLess(content.index("Trivy scan exact image before publication"), content.index("Push exact scanned OCI image"))
        self.assertLess(content.index("Push exact scanned OCI image"), content.index("Verify registry digest against running container imageID"))
        self.assertLess(content.index("Verify registry digest against running container imageID"), content.index("Generate OCI SLSA provenance attestation"))

    def test_release_manifest_never_calls_green_ci_production_verified(self):
        content = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn('status="ATTESTED_PENDING_HUMAN"', content)
        self.assertNotIn('status="VERIFIED"', content)
        self.assertIn('python -m unittest discover -s tests -p "test_release_source_binding.py"', content)

    def test_runtime_image_source_is_embedded_and_not_environment_asserted(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        nina = (ROOT / ".github/workflows/nina-igor-ollama.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        runtime = (ROOT / "app/runtime_provenance.py").read_text(encoding="utf-8")
        self.assertIn("org.opencontainers.image.revision", dockerfile)
        self.assertIn("chown -R root:root /app", dockerfile)
        self.assertIn("chmod -R a-w /app", dockerfile)
        self.assertIn("ola-build-info.json", dockerfile)
        self.assertIn("--build-arg OLA_SOURCE_COMMIT=", nina)
        self.assertIn("OLA_REQUIRE_BUILD_INFO=1", nina)
        self.assertIn("0000000000000000000000000000000000000000", nina)
        self.assertIn("--build-arg OLA_SOURCE_COMMIT=", release)
        self.assertIn("Assert release image source label", release)
        self.assertIn("OLA_REQUIRE_BUILD_INFO=1", release)
        self.assertIn("/readyz", release)
        self.assertIn("RELEASE_IMAGE_SOURCE_BINDING=VERIFIED", release)
        self.assertIn("build_info_mutable", (ROOT / "app/main.py").read_text(encoding="utf-8"))
        self.assertIn("OLA_RUNTIME_COMMIT is a compatibility fallback", runtime)

    def test_automated_runtime_never_claims_human_approval(self):
        proof = (ROOT / ".github/workflows/nina-real-runtime-provenance.yml").read_text(encoding="utf-8")
        igor = (ROOT / ".github/workflows/igor-independent-evidence.yml").read_text(encoding="utf-8")
        self.assertIn('"human_gate":"PENDING"', proof)
        self.assertNotIn('"human_gate":"VERIFIED"', proof)
        self.assertIn('assert d["human_gate"]=="PENDING"', proof)
        self.assertIn('assert record_hash==hashlib.sha256(', proof)
        self.assertNotIn('assert record_hash==api_key_fingerprint(', proof)
        self.assertIn('assert d["human_gate"]=="PENDING"', igor)

    def test_pull_request_manifest_never_claims_attestation(self):
        content = (ROOT / ".github/workflows/final-production-gate.yml").read_text(encoding="utf-8")
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main' && success()", content)
        self.assertIn('source_attestation="NOT_PERFORMED"', content)
        self.assertIn('image_attestation="NOT_PERFORMED"', content)
        self.assertIn('status="PREMERGE_CI_PASSED"', content)


if __name__ == "__main__":
    unittest.main()
