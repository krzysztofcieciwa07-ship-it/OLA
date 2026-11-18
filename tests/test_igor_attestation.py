from __future__ import annotations

import hashlib
import io
import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.igor_attestation import (
    _PREDICATE_TYPE,
    build_predicate,
    resolve_flow_run,
    verify_attestation_data,
    verify_igor_bundle,
)


SOURCE_SHA = "a" * 40
REPOSITORY = "krzysztofcieciwa07-ship-it/OLA"
FLOW_PATH = ".github/workflows/ola-12h-autoflow.yml"
FINAL_PATH = ".github/workflows/final-production-gate.yml"
FINAL_NAME = "OLA FINAL PRODUCTION GATE"


def _bundle_files(source_sha: str) -> dict[str, bytes]:
    manifest = {
        "schema": "ola-igor-evidence/v1",
        "source_commit": source_sha,
        "nina_run_id": 123,
        "tenant_id": "tenant-1",
        "run_id": "run-1",
        "provider": "ollama",
        "model": "qwen2.5:0.5b-instruct",
        "igor": "VERIFIED",
        "tamper": "BLOCK",
        "human_gate": "PENDING",
    }
    result = {
        "status": "VERIFIED",
        "verifier": "IGOR",
        "source_commit": source_sha,
        "nina_run_id": 123,
        "nina_artifact_name": f"nina-evidence-{source_sha}",
        "provider": "ollama",
        "model": "qwen2.5:0.5b-instruct",
        "evidence_count": 6,
        "hash_chain": "VERIFIED",
        "tamper": "BLOCK",
        "replay": "VERIFIED",
        "human_gate": "PENDING",
    }
    files = {
        "evidence-bundle/source/commit.txt": f"{source_sha}\n".encode(),
        "evidence-bundle/MANIFEST.json": (json.dumps(manifest, sort_keys=True) + "\n").encode(),
        "evidence-bundle/verification/igor-result.json": (json.dumps(result, sort_keys=True) + "\n").encode(),
        "evidence-bundle/human/human-gate.json": b'{"status":"PENDING"}\n',
    }
    checksum_lines = [
        f"{hashlib.sha256(payload).hexdigest()}  {name}"
        for name, payload in sorted(files.items())
    ]
    files["evidence-bundle/integrity/bundle-files.sha256"] = ("\n".join(checksum_lines) + "\n").encode()
    return files


def _write_bundle(directory: Path, source_sha: str = SOURCE_SHA, *, malicious_name: str | None = None):
    files = _bundle_files(source_sha)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        root = tarfile.TarInfo("evidence-bundle/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if malicious_name:
            info = tarfile.TarInfo(malicious_name)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    bundle = directory / "igor-ollama-evidence-bundle.tar.gz"
    bundle.write_bytes(buffer.getvalue())
    checksum = directory / "igor-ollama-evidence-bundle.sha256"
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")
    return bundle, checksum


def _valid_predicate(source_sha: str, flow_run_id: int, final_run_id: int, subject_sha: str):
    return {
        "schema": _PREDICATE_TYPE,
        "source": {"repository": REPOSITORY, "commit": source_sha},
        "workflow": {
            "path": FINAL_PATH,
            "ref": "refs/heads/main",
            "trigger": "push",
            "run_id": final_run_id,
        },
        "producer": {
            "workflow_path": FLOW_PATH,
            "run_id": flow_run_id,
            "artifact_name": f"ola-auto-evidence-{source_sha}",
        },
        "evidence": {
            "bundle_sha256": subject_sha,
            "manifest_sha256": "b" * 64,
            "result_sha256": "c" * 64,
            "auto_evidence_sha256": "d" * 64,
            "status": "VERIFIED",
            "hash_chain": "VERIFIED",
            "tamper": "BLOCK",
            "replay": "VERIFIED",
            "human_gate": "PENDING",
            "provider": "ollama",
            "model": "qwen2.5:0.5b-instruct",
            "evidence_count": 6,
        },
    }


def _attestation(source_sha: str, flow_run_id: int, final_run_id: int, subject_sha: str, *, trigger: str = "push"):
    signer = f"https://github.com/{REPOSITORY}/{FINAL_PATH}@refs/heads/main"
    predicate = _valid_predicate(source_sha, flow_run_id, final_run_id, subject_sha)
    certificate = {
        "sourceRepositoryDigest": source_sha,
        "sourceRepositoryURI": f"https://github.com/{REPOSITORY}",
        "sourceRepositoryRef": "refs/heads/main",
        "githubWorkflowSHA": source_sha,
        "githubWorkflowRepository": REPOSITORY,
        "githubWorkflowRef": "refs/heads/main",
        "githubWorkflowTrigger": trigger,
        "githubWorkflowName": FINAL_NAME,
        "buildSignerURI": signer,
        "buildConfigURI": signer,
    }
    return [{
        "verificationResult": {
            "signature": {"certificate": certificate},
            "verifiedIdentity": {"subjectAlternativeName": signer},
            "verifiedTimestamps": [{"type": "Tlog", "uri": "https://rekor.sigstore.dev"}],
            "statement": {
                "_type": "https://in-toto.io/Statement/v1",
                "predicateType": _PREDICATE_TYPE,
                "subject": [{"name": "igor-ollama-evidence-bundle.tar.gz", "digest": {"sha256": subject_sha}}],
                "predicate": predicate,
            },
        }
    }]


class IgorBundleAttestationTests(unittest.TestCase):
    def test_verifies_outer_and_inner_bundle_hashes_and_igor_claims(self):
        with TemporaryDirectory() as tmp:
            bundle, checksum = _write_bundle(Path(tmp))
            result = verify_igor_bundle(bundle, checksum, SOURCE_SHA)
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual("BLOCK", result["tamper"])
        self.assertEqual("VERIFIED", result["replay"])
        self.assertEqual("PENDING", result["human_gate"])

    def test_rejects_outer_checksum_mismatch(self):
        with TemporaryDirectory() as tmp:
            bundle, checksum = _write_bundle(Path(tmp))
            bundle.write_bytes(bundle.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_igor_bundle(bundle, checksum, SOURCE_SHA)

    def test_rejects_internal_file_mutation_even_with_new_outer_checksum(self):
        with TemporaryDirectory() as tmp:
            bundle, checksum = _write_bundle(Path(tmp))
            raw = bundle.read_bytes()
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                members = archive.getmembers()
                payloads = {m.name: archive.extractfile(m).read() for m in members if m.isfile()}
            payloads["evidence-bundle/human/human-gate.json"] = b'{"status":"APPROVED"}\n'
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                root = tarfile.TarInfo("evidence-bundle/")
                root.type = tarfile.DIRTYPE
                archive.addfile(root)
                for name, payload in payloads.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            bundle.write_bytes(buffer.getvalue())
            checksum.write_text(
                f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "internal checksum mismatch"):
                verify_igor_bundle(bundle, checksum, SOURCE_SHA)

    def test_rejects_path_traversal_member(self):
        with TemporaryDirectory() as tmp:
            bundle, checksum = _write_bundle(Path(tmp), malicious_name="evidence-bundle/../escape")
            with self.assertRaisesRegex(ValueError, "path traversal"):
                verify_igor_bundle(bundle, checksum, SOURCE_SHA)

    def test_rejects_source_sha_mismatch(self):
        with TemporaryDirectory() as tmp:
            bundle, checksum = _write_bundle(Path(tmp))
            with self.assertRaisesRegex(ValueError, "source"):
                verify_igor_bundle(bundle, checksum, "b" * 40)

    def test_resolves_only_the_exact_main_push_flow_and_nested_igor_job(self):
        flow = {
            "id": 1001,
            "name": "OLA 12h Autonomous Evidence Flow",
            "path": FLOW_PATH,
            "workflow_id": 55,
            "head_sha": SOURCE_SHA,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        gate_status = {
            "exact_source_gates": {
                "OLA 12h Autonomous Evidence Flow": {
                    "id": 1001,
                    "path": FLOW_PATH,
                    "workflow_id": 55,
                    "head_sha": SOURCE_SHA,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                "IGOR Independent Ollama Evidence Gate": {
                    "id": 2001,
                    "head_sha": SOURCE_SHA,
                    "status": "completed",
                    "conclusion": "success",
                },
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "required-runs.json").write_text(json.dumps({"workflow_runs": [flow]}), encoding="utf-8")
            (root / "gate-status.json").write_text(json.dumps(gate_status), encoding="utf-8")
            result = resolve_flow_run(root / "required-runs.json", root / "gate-status.json", SOURCE_SHA)
        self.assertEqual(1001, result)

    def test_rejects_same_sha_push_from_non_main_branch(self):
        flow = {
            "id": 1001,
            "name": "OLA 12h Autonomous Evidence Flow",
            "path": FLOW_PATH,
            "workflow_id": 55,
            "head_sha": SOURCE_SHA,
            "head_branch": "fix/igor-main-attestation-20261118",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        gate_status = {
            "exact_source_gates": {
                "OLA 12h Autonomous Evidence Flow": {
                    "id": 1001,
                    "path": FLOW_PATH,
                    "workflow_id": 55,
                    "head_sha": SOURCE_SHA,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                "IGOR Independent Ollama Evidence Gate": {
                    "id": 2001,
                    "head_sha": SOURCE_SHA,
                    "status": "completed",
                    "conclusion": "success",
                },
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "required-runs.json").write_text(json.dumps({"workflow_runs": [flow]}), encoding="utf-8")
            (root / "gate-status.json").write_text(json.dumps(gate_status), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "head_branch"):
                resolve_flow_run(root / "required-runs.json", root / "gate-status.json", SOURCE_SHA)

    def test_verifies_exact_main_sigstore_identity_and_predicate(self):
        subject_sha = "e" * 64
        data = _attestation(SOURCE_SHA, 1001, 2001, subject_sha)
        result = verify_attestation_data(
            data,
            expected_source_sha=SOURCE_SHA,
            expected_repository=REPOSITORY,
            expected_flow_run_id=1001,
            expected_final_run_id=2001,
            expected_subject_sha256=subject_sha,
        )
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual("PENDING", result["human_gate"])

    def test_rejects_pull_request_attestation(self):
        data = _attestation(SOURCE_SHA, 1001, 2001, "e" * 64, trigger="pull_request")
        with self.assertRaisesRegex(ValueError, "no Sigstore attestation"):
            verify_attestation_data(
                data,
                expected_source_sha=SOURCE_SHA,
                expected_repository=REPOSITORY,
                expected_flow_run_id=1001,
                expected_final_run_id=2001,
                expected_subject_sha256="e" * 64,
            )

    def test_rejects_wrong_flow_run_identity(self):
        data = _attestation(SOURCE_SHA, 1001, 2001, "e" * 64)
        with self.assertRaisesRegex(ValueError, "no Sigstore attestation"):
            verify_attestation_data(
                data,
                expected_source_sha=SOURCE_SHA,
                expected_repository=REPOSITORY,
                expected_flow_run_id=1002,
                expected_final_run_id=2001,
                expected_subject_sha256="e" * 64,
            )

    def test_builds_predicate_with_exact_run_and_bundle_digests(self):
        info = {
            "bundle_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "result_sha256": "c" * 64,
            "model": "qwen2.5:0.5b-instruct",
        }
        result = build_predicate(
            source_sha=SOURCE_SHA,
            repository=REPOSITORY,
            final_run_id=2001,
            flow_run_id=1001,
            auto_evidence_sha256="d" * 64,
            bundle_info=info,
        )
        self.assertEqual(1001, result["producer"]["run_id"])
        self.assertEqual("a" * 64, result["evidence"]["bundle_sha256"])
        self.assertEqual("PENDING", result["evidence"]["human_gate"])


if __name__ == "__main__":
    unittest.main()
