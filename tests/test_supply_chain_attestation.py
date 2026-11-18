from pathlib import Path
import unittest

from scripts.verify_supply_chain_attestation import verify_attestation_data


ROOT = Path(__file__).resolve().parents[1]
SLSA = "https://slsa.dev/provenance/v1"


def make_attestation(source_sha, subject_sha, *, workflow_ref="refs/heads/main", trigger="push"):
    repository = "krzysztofcieciwa07-ship-it/OLA"
    workflow_path = ".github/workflows/supply-chain-evidence.yml"
    signer = f"https://github.com/{repository}/{workflow_path}@{workflow_ref}"
    return [{
        "verificationResult": {
            "signature": {
                "certificate": {
                    "sourceRepositoryDigest": source_sha,
                    "sourceRepositoryURI": f"https://github.com/{repository}",
                    "sourceRepositoryRef": workflow_ref,
                    "githubWorkflowSHA": source_sha,
                    "githubWorkflowRepository": repository,
                    "githubWorkflowRef": workflow_ref,
                    "githubWorkflowTrigger": trigger,
                    "githubWorkflowName": "OLA Supply Chain Evidence Gate",
                    "buildSignerURI": signer,
                    "buildConfigURI": signer,
                }
            },
            "verifiedIdentity": {"subjectAlternativeName": signer},
            "verifiedTimestamps": [{"type": "Tlog", "uri": "https://rekor.sigstore.dev"}],
            "statement": {
                "_type": "https://in-toto.io/Statement/v1",
                "predicateType": SLSA,
                "subject": [{"name": "ola-image.tar", "digest": {"sha256": subject_sha}}],
                "predicate": {
                    "buildDefinition": {
                        "externalParameters": {
                            "workflow": {
                                "path": workflow_path,
                                "ref": workflow_ref,
                                "repository": f"https://github.com/{repository}",
                            }
                        },
                        "resolvedDependencies": [
                            {"uri": f"git+https://github.com/{repository}@{workflow_ref}",
                             "digest": {"gitCommit": source_sha}}
                        ]
                    }
                }
            }
        }
    }]


class SupplyChainAttestationTests(unittest.TestCase):
    def setUp(self):
        self.source_sha = "a" * 40
        self.subject_sha = "b" * 64
        self.expected = {
            "expected_source_sha": self.source_sha,
            "expected_repository": "krzysztofcieciwa07-ship-it/OLA",
            "expected_workflow_path": ".github/workflows/supply-chain-evidence.yml",
            "expected_workflow_ref": "refs/heads/main",
            "expected_subject_sha256": self.subject_sha,
        }

    def test_accepts_exact_main_source_and_image_subject(self):
        result = verify_attestation_data(
            make_attestation(self.source_sha, self.subject_sha),
            **self.expected,
        )
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual(self.source_sha, result["source_sha"])
        self.assertEqual(self.subject_sha, result["subject_sha256"])

    def test_rejects_pr_merge_commit_instead_of_expected_head(self):
        merge_sha = "c" * 40
        data = make_attestation(merge_sha, self.subject_sha)
        with self.assertRaises(ValueError):
            verify_attestation_data(data, **self.expected)

    def test_rejects_subject_digest_mismatch(self):
        data = make_attestation(self.source_sha, "d" * 64)
        with self.assertRaises(ValueError):
            verify_attestation_data(data, **self.expected)

    def test_rejects_non_main_workflow_ref(self):
        data = make_attestation(
            self.source_sha,
            self.subject_sha,
            workflow_ref="refs/pull/253/merge",
        )
        with self.assertRaises(ValueError):
            verify_attestation_data(data, **self.expected)

    def test_rejects_pull_request_trigger(self):
        data = make_attestation(
            self.source_sha,
            self.subject_sha,
            trigger="pull_request",
        )
        with self.assertRaises(ValueError):
            verify_attestation_data(data, **self.expected)

    def test_rejects_unverified_identity(self):
        data = make_attestation(self.source_sha, self.subject_sha)
        data[0]["verificationResult"]["verifiedIdentity"] = {}
        with self.assertRaises(ValueError):
            verify_attestation_data(data, **self.expected)

    def test_supply_chain_workflow_limits_attestation_permissions_to_main(self):
        workflow = (ROOT / ".github" / "workflows" / "supply-chain-evidence.yml").read_text(encoding="utf-8")
        self.assertIn('docker build --pull --build-arg OLA_SOURCE_COMMIT="$EXPECTED_SOURCE_SHA"', workflow)
        self.assertIn("image_source=", workflow)
        security_job = workflow.split("  security-image:\n", 1)[1]
        if "  attest-main:\n" in security_job:
            security_job = security_job.split("  attest-main:\\n", 1)[0]
        self.assertNotIn("attestations: write", security_job)
        self.assertNotIn("id-token: write", security_job)
        self.assertNotIn("Generate SLSA provenance attestation", security_job)
        self.assertIn("  attest-main:", workflow)
        attest_job = workflow.split("  attest-main:", 1)[1]
        self.assertIn("if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'", attest_job)
        self.assertIn("attestations: write", attest_job)
        self.assertIn("id-token: write", attest_job)
        self.assertIn("actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093", attest_job)
        self.assertIn("verify_supply_chain_attestation.py", attest_job)


if __name__ == "__main__":
    unittest.main()
