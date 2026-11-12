import json
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_oci_attestation import VerificationError, verify_oci_attestation

IMAGE = "ghcr.io/krzysztofcieciwa07-ship-it/ola-di-os"
DIGEST = "sha256:" + ("a" * 64)
SOURCE_SHA = "b" * 40
REPOSITORY = "krzysztofcieciwa07-ship-it/OLA"
SIGNER = f"{REPOSITORY}/.github/workflows/ola-oci-release.yml"
SLSA = "https://slsa.dev/provenance/v1"


def good_payload(image=IMAGE, digest=DIGEST, predicate_type=SLSA):
    return [{
        "verificationResult": {
            "statement": {
                "predicateType": predicate_type,
                "subject": [{
                    "name": image,
                    "digest": {"sha256": digest.removeprefix("sha256:")},
                }],
            }
        }
    }]


class VerifyOciAttestationTests(unittest.TestCase):
    @patch("verify_oci_attestation.subprocess.run")
    def test_accepts_only_exact_image_digest_and_build_identity(self, run):
        run.return_value = CompletedProcess([], 0, json.dumps(good_payload()), "")

        result = verify_oci_attestation(
            image=IMAGE,
            digest=DIGEST,
            repository=REPOSITORY,
            signer_workflow=SIGNER,
            source_ref="refs/heads/main",
            source_sha=SOURCE_SHA,
        )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["image_ref"], f"{IMAGE}@{DIGEST}")
        command = run.call_args.args[0]
        self.assertIn(f"oci://{IMAGE}@{DIGEST}", command)
        self.assertEqual(command[command.index("--source-digest") + 1], SOURCE_SHA)
        self.assertIn("--signer-workflow", command)
        self.assertIn(SIGNER, command)

    @patch("verify_oci_attestation.subprocess.run")
    def test_blocks_subject_digest_mismatch(self, run):
        bad_digest = "sha256:" + ("c" * 64)
        run.return_value = CompletedProcess([], 0, json.dumps(good_payload(digest=bad_digest)), "")
        with self.assertRaises(VerificationError):
            verify_oci_attestation(IMAGE, DIGEST, REPOSITORY, SIGNER, "refs/heads/main", SOURCE_SHA)

    @patch("verify_oci_attestation.subprocess.run")
    def test_blocks_wrong_predicate_type(self, run):
        run.return_value = CompletedProcess([], 0, json.dumps(good_payload(predicate_type="https://example.invalid/claim")), "")
        with self.assertRaises(VerificationError):
            verify_oci_attestation(IMAGE, DIGEST, REPOSITORY, SIGNER, "refs/heads/main", SOURCE_SHA)

    @patch("verify_oci_attestation.subprocess.run")
    def test_propagates_cryptographic_verification_failure(self, run):
        run.return_value = CompletedProcess([], 1, "", "signature verification failed")
        with self.assertRaises(VerificationError):
            verify_oci_attestation(IMAGE, DIGEST, REPOSITORY, SIGNER, "refs/heads/main", SOURCE_SHA)

    @patch("verify_oci_attestation.subprocess.run")
    def test_rejects_invalid_digest_before_calling_gh(self, run):
        with self.assertRaises(ValueError):
            verify_oci_attestation(IMAGE, "sha256:abc", REPOSITORY, SIGNER, "refs/heads/main", SOURCE_SHA)
        run.assert_not_called()

    @patch("verify_oci_attestation.subprocess.run")
    def test_rejects_mutable_tag_as_image_name(self, run):
        with self.assertRaises(ValueError):
            verify_oci_attestation(IMAGE + ":latest", DIGEST, REPOSITORY, SIGNER, "refs/heads/main", SOURCE_SHA)
        run.assert_not_called()

    @patch("verify_oci_attestation.subprocess.run")
    def test_rejects_invalid_source_sha_before_calling_gh(self, run):
        with self.assertRaises(ValueError):
            verify_oci_attestation(IMAGE, DIGEST, REPOSITORY, SIGNER, "refs/heads/main", "bad-sha")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
