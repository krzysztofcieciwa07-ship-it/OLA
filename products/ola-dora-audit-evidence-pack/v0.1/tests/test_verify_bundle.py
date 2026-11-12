import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_bundle import canonical_digest, load_catalogue, validate_bundle


class EvidenceBundleTests(unittest.TestCase):
    def base_bundle(self):
        return {
            "schema": "ola-evidence-bundle-v0.1",
            "repository": "example-org/payments-api",
            "change_id": "CHG-001",
            "commit_sha": "0123456789abcdef0123456789abcdef01234567",
            "artifact_digest": "sha256:" + "a" * 64,
            "controls": []
        }

    def test_missing_controls_remain_unknown_and_manifest_not_ready(self):
        manifest = validate_bundle(self.base_bundle())
        self.assertEqual(manifest["summary"]["status"], "NOT_READY")
        self.assertEqual(manifest["summary"]["control_counts"]["UNKNOWN"], 12)
        self.assertEqual(manifest["attestation"]["status"], "NOT_ISSUED")

    def test_skipped_control_never_counts_as_pass(self):
        bundle = self.base_bundle()
        cid = next(iter(load_catalogue()))
        bundle["controls"] = [{"control_id": cid, "status": "SKIPPED", "exception_reason": "out of pilot scope"}]
        manifest = validate_bundle(bundle)
        result = next(x for x in manifest["controls"] if x["control_id"] == cid)
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(manifest["summary"]["status"], "NOT_READY")

    def test_not_applicable_never_counts_as_pass(self):
        bundle = self.base_bundle()
        cid = next(iter(load_catalogue()))
        bundle["controls"] = [{"control_id": cid, "status": "NOT_APPLICABLE", "approval_status": "APPROVED", "evidence": []}]
        manifest = validate_bundle(bundle)
        result = next(x for x in manifest["controls"] if x["control_id"] == cid)
        self.assertEqual(result["status"], "NOT_APPLICABLE")
        self.assertNotEqual(manifest["summary"]["status"], "READY")

    def test_tampered_evidence_payload_is_invalid(self):
        bundle = self.base_bundle()
        cid, control = next(iter(load_catalogue().items()))
        evidence = [{"type": required, "payload": {"source": "fixture"}, "sha256": "sha256:" + "0" * 64} for required in control["required_evidence"]]
        bundle["controls"] = [{"control_id": cid, "status": "PASS", "approval_status": "APPROVED", "evidence": evidence}]
        manifest = validate_bundle(bundle)
        result = next(x for x in manifest["controls"] if x["control_id"] == cid)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["evidence_integrity"], "INVALID")

    def test_pass_is_downgraded_when_required_evidence_is_missing(self):
        bundle = self.base_bundle()
        cid = next(iter(load_catalogue()))
        bundle["controls"] = [{"control_id": cid, "status": "PASS", "approval_status": "APPROVED", "evidence": []}]
        manifest = validate_bundle(bundle)
        result = next(x for x in manifest["controls"] if x["control_id"] == cid)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotEqual(manifest["summary"]["status"], "READY")

    def test_manifest_digest_is_recomputable(self):
        manifest = validate_bundle(self.base_bundle())
        claimed = manifest["manifest_digest"]
        digest_input = dict(manifest)
        digest_input.pop("manifest_digest")
        self.assertEqual(claimed, canonical_digest(digest_input))


if __name__ == "__main__":
    unittest.main()
