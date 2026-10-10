"""Executable NO-GO policy tests; no GitHub network or secrets required."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from assert_manifest_policy import PolicyError,validate

SOURCE="a"*40
MERGE="b"*40
GATES=["ci","state-continuity","stability","provenance","signatures",
       "real-runtime","stress","tamper","replay","human-gate"]

def fixture(event="pull_request",state="BLOCKED"):
    return {"schema":"ola-production-evidence-v1","commit":SOURCE,
            "workflow_event":event,"workflow_event_sha":MERGE if event=="pull_request" else SOURCE,
            "commit_signature_gate":"BLOCKED","source_snapshot":None,"release_image":None,
            "source_attestation":"NOT_PERFORMED","image_attestation":"NOT_PERFORMED",
            "required_gates":list(GATES),"human_gate":"PENDING",
            "production_deployment":"NOT_PERFORMED","go_no_go":"NO-GO","final_status":state}

class ManifestPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def call(self,m,event="pull_request",ref="refs/pull/66/merge"):
        return validate(m,source=SOURCE,event=event,
                        event_sha=MERGE if event=="pull_request" else SOURCE,
                        ref=ref,root=self.root)
    def ci(self,wrong_sha=False):
        (self.root/"gate-status.json").write_text(json.dumps({
            "missing":[],"pending":{},"failed":{},
            "exact_source_gates":{"E2E":{"status":"completed","conclusion":"success",
                                          "head_sha":"f"*40 if wrong_sha else SOURCE}},
            "reference_gates":{"BASE":{"status":"completed","conclusion":"success"}}}))
    def pr_signed(self):
        m=fixture(state="PREMERGE_CI_PASSED")
        m.update(commit_signature_gate="AUTHORIZED_GPG_VERIFIED",
                 source_attestation="PR_ONLY_NOT_RELEASE",image_attestation="PR_ONLY_NOT_RELEASE")
        (self.root/"signature-gate-result.json").write_text(json.dumps({
            "status":"VERIFIED","head_sha":SOURCE,"verified_count":13,"production_go":"NO-GO"}))
        self.ci()
        return m
    def main_attested(self):
        m=fixture(event="push",state="ATTESTED_PENDING_HUMAN")
        m.update(commit_signature_gate="GITHUB_COMMIT_VERIFIED",
                 source_snapshot=f"ola-source-{SOURCE}.tar.gz",
                 release_image="ola-release-image.tar",
                 source_attestation="VERIFIED",image_attestation="VERIFIED")
        (self.root/"main-signature-result.json").write_text(json.dumps({
            "status":"VERIFIED","head_sha":SOURCE,"verified_count":2,"production_go":"NO-GO"}))
        for name,sumfile in ((m["source_snapshot"],"source-sha256.txt"),
                             ("ola-release-image.tar","image-sha256.txt")):
            payload=("valid "+name).encode()
            (self.root/name).write_bytes(payload)
            (self.root/sumfile).write_text(hashlib.sha256(payload).hexdigest()+"  "+name+"\n")
        self.ci()
        return m
    def blocked(self,m,match):
        with self.assertRaisesRegex(PolicyError,match):self.call(m)
    def test_blocked_pr_is_not_verified(self):
        self.assertEqual(self.call(fixture()),"BLOCKED")
    def test_green_ci_does_not_make_verification(self):
        self.ci();self.blocked(fixture(state="VERIFIED"),"false production")
    def test_human_approval_cannot_be_invented(self):
        m=fixture();m["human_gate"]="VERIFIED";self.blocked(m,"Human Gate")
    def test_go_no_go_cannot_be_overridden(self):
        m=fixture();m["go_no_go"]="GO";self.blocked(m,"production GO")
    def test_duplicate_or_missing_required_gate(self):
        m=fixture();m["required_gates"].remove("human-gate");self.blocked(m,"evidence gates")
    def test_pr_premerge_requires_signature(self):
        self.blocked(fixture(state="PREMERGE_CI_PASSED"),"signature gate")
    def test_pr_cannot_claim_attested_release(self):
        self.blocked(fixture(state="ATTESTED_PENDING_HUMAN"),"PR cannot")
    def test_pr_cannot_claim_release_file(self):
        m=fixture();m["release_image"]="fake";self.blocked(m,"PR cannot")
    def test_signed_pr_positive_remains_nonproduction(self):
        self.assertEqual(self.call(self.pr_signed()),"PREMERGE_CI_PASSED")
    def test_signed_pr_wrong_source_blocked(self):
        m=self.pr_signed()
        p=json.loads((self.root/"signature-gate-result.json").read_text())
        p["head_sha"]="f"*40
        (self.root/"signature-gate-result.json").write_text(json.dumps(p))
        self.blocked(m,"unbound PR GPG")
    def test_signature_without_ci_rejected(self):
        m=self.pr_signed();(self.root/"gate-status.json").unlink()
        self.blocked(m,"evidence unavailable")
    def test_wrong_ci_sha_rejected(self):
        m=self.pr_signed();self.ci(wrong_sha=True)
        self.blocked(m,"CI source SHA drift")
    def test_unsigned_main_attestation_rejected(self):
        with self.assertRaisesRegex(PolicyError,"main signer"):
            self.call(fixture(event="push",state="ATTESTED_PENDING_HUMAN"),
                      event="push",ref="refs/heads/main")
    def test_signed_main_attestation_not_human_approved(self):
        self.assertEqual(self.call(self.main_attested(),event="push",
                                   ref="refs/heads/main"),"ATTESTED_PENDING_HUMAN")
    def test_modified_attested_image_detected(self):
        m=self.main_attested()
        (self.root/"ola-release-image.tar").write_bytes(b"tampered")
        with self.assertRaisesRegex(PolicyError,"digest mismatch"):
            self.call(m,event="push",ref="refs/heads/main")
    def test_main_wrong_branch(self):
        with self.assertRaisesRegex(PolicyError,"exact main push"):
            self.call(fixture(event="push"),event="push",ref="refs/heads/other")
    def test_manual_dispatch_must_block(self):
        self.assertEqual(self.call(fixture(event="workflow_dispatch"),event="workflow_dispatch",ref="refs/heads/main"),"BLOCKED")
