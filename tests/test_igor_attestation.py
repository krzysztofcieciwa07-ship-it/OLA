from __future__ import annotations

import hashlib
import io
import json
import tarfile
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

import scripts.igor_attestation as igor_attestation

from scripts.igor_attestation import (
    _PREDICATE_TYPE,
    build_predicate,
    resolve_flow_run,
    verify_attestation_data,
    verify_auto_evidence,
    verify_igor_bundle,
    _read_tar_files,
    resolve_artifact_bindings,
)


SOURCE_SHA = "a" * 40
REPOSITORY = "krzysztofcieciwa07-ship-it/OLA"
FLOW_PATH = ".github/workflows/ola-12h-autoflow.yml"
FINAL_PATH = ".github/workflows/final-production-gate.yml"
FINAL_NAME = "OLA FINAL PRODUCTION GATE"
AUTO_ARTIFACT_ID = 10001
IGOR_ARTIFACT_ID = 10002
AUTO_ARTIFACT_DIGEST = "sha256:" + "d" * 64
IGOR_ARTIFACT_DIGEST = "sha256:" + "e" * 64


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
            "auto_artifact": {
                "id": AUTO_ARTIFACT_ID,
                "name": f"ola-auto-evidence-{source_sha}",
                "archive_digest": AUTO_ARTIFACT_DIGEST,
            },
            "igor_artifact": {
                "id": IGOR_ARTIFACT_ID,
                "name": f"igor-independent-ollama-evidence-{source_sha}",
                "archive_digest": IGOR_ARTIFACT_DIGEST,
            },
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

    def test_rejects_oversized_bundle_before_unbounded_read(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "igor-ollama-evidence-bundle.tar.gz"
            checksum = root / "igor-ollama-evidence-bundle.sha256"
            bundle.write_bytes(b"x" * 128)
            checksum.write_text("0" * 64 + "  " + bundle.name + "\n", encoding="utf-8")

            with patch.object(igor_attestation, "_MAX_ARCHIVE_BYTES", 64):
                with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")):
                    with self.assertRaisesRegex(ValueError, "compressed-size limit"):
                        verify_igor_bundle(bundle, checksum, SOURCE_SHA)

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

    def test_rejects_pax_metadata_that_exceeds_decompressed_tar_stream_budget(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            info = tarfile.TarInfo("evidence-bundle/MANIFEST.json")
            info.pax_headers = {"comment": "x" * (1024 * 1024)}
            payload = b'{"ok":true}'
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

        # Keep the test small while proving that PAX extension data is charged
        # against the decompressed stream budget, not just regular-file sizes.
        with patch.object(igor_attestation, "_MAX_TAR_STREAM_BYTES", 64 * 1024, create=True):
            with self.assertRaisesRegex(ValueError, "decompressed TAR stream limit"):
                _read_tar_files(buffer.getvalue())

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
                    "html_url": f"https://github.com/{REPOSITORY}/actions/runs/1001/job/2001",
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
            result = resolve_flow_run(root / "required-runs.json", root / "gate-status.json", SOURCE_SHA, REPOSITORY)
        self.assertEqual(1001, result)

    def test_rejects_nested_igor_job_from_a_different_flow_run(self):
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
                    "html_url": f"https://github.com/{REPOSITORY}/actions/runs/9999/job/2001",
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
            with self.assertRaisesRegex(ValueError, "not bound to the exact 12h flow run"):
                resolve_flow_run(root / "required-runs.json", root / "gate-status.json", SOURCE_SHA, REPOSITORY)

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
                resolve_flow_run(root / "required-runs.json", root / "gate-status.json", SOURCE_SHA, REPOSITORY)

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
            expected_igor_artifact_id=IGOR_ARTIFACT_ID,
            expected_igor_artifact_digest=IGOR_ARTIFACT_DIGEST,
            expected_auto_artifact_id=AUTO_ARTIFACT_ID,
            expected_auto_artifact_digest=AUTO_ARTIFACT_DIGEST,
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
                expected_igor_artifact_id=IGOR_ARTIFACT_ID,
                expected_igor_artifact_digest=IGOR_ARTIFACT_DIGEST,
                expected_auto_artifact_id=AUTO_ARTIFACT_ID,
                expected_auto_artifact_digest=AUTO_ARTIFACT_DIGEST,
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
                expected_igor_artifact_id=IGOR_ARTIFACT_ID,
                expected_igor_artifact_digest=IGOR_ARTIFACT_DIGEST,
                expected_auto_artifact_id=AUTO_ARTIFACT_ID,
                expected_auto_artifact_digest=AUTO_ARTIFACT_DIGEST,
            )

    def test_builds_predicate_with_exact_run_and_bundle_digests(self):
        info = {
            "bundle_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "result_sha256": "c" * 64,
            "model": "qwen2.5:0.5b-instruct",
            "igor_artifact_id": IGOR_ARTIFACT_ID,
            "igor_artifact_name": f"igor-independent-ollama-evidence-{SOURCE_SHA}",
            "igor_artifact_digest": IGOR_ARTIFACT_DIGEST,
            "auto_artifact_id": AUTO_ARTIFACT_ID,
            "auto_artifact_name": f"ola-auto-evidence-{SOURCE_SHA}",
            "auto_artifact_digest": AUTO_ARTIFACT_DIGEST,
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
        self.assertEqual(IGOR_ARTIFACT_ID, result["producer"]["igor_artifact"]["id"])
        self.assertEqual(AUTO_ARTIFACT_ID, result["producer"]["auto_artifact"]["id"])
        self.assertEqual("a" * 64, result["evidence"]["bundle_sha256"])
        self.assertEqual("PENDING", result["evidence"]["human_gate"])


    def test_build_predicate_binds_exact_github_artifact_ids_and_archive_digests(self):
        info = {
            "bundle_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "result_sha256": "c" * 64,
            "model": "qwen2.5:0.5b-instruct",
            "igor_artifact_id": 14458759888,
            "igor_artifact_name": f"igor-independent-ollama-evidence-{SOURCE_SHA}",
            "igor_artifact_digest": "sha256:" + "d" * 64,
            "auto_artifact_id": 14459024940,
            "auto_artifact_name": f"ola-auto-evidence-{SOURCE_SHA}",
            "auto_artifact_digest": "sha256:" + "e" * 64,
        }
        result = build_predicate(
            source_sha=SOURCE_SHA,
            repository=REPOSITORY,
            final_run_id=2001,
            flow_run_id=1001,
            auto_evidence_sha256="f" * 64,
            bundle_info=info,
        )
        producer = result["producer"]
        self.assertEqual(14458759888, producer["igor_artifact"]["id"])
        self.assertEqual("sha256:" + "d" * 64, producer["igor_artifact"]["archive_digest"])
        self.assertEqual(14459024940, producer["auto_artifact"]["id"])
        self.assertEqual("sha256:" + "e" * 64, producer["auto_artifact"]["archive_digest"])


    def test_resolves_exact_main_artifact_ids_and_archive_digests(self):
        flow_run_id = 1001
        rows = [
            {
                "id": AUTO_ARTIFACT_ID,
                "name": f"ola-auto-evidence-{SOURCE_SHA}",
                "digest": AUTO_ARTIFACT_DIGEST,
                "size_in_bytes": 123,
                "expired": False,
                "workflow_run": {"id": flow_run_id, "head_sha": SOURCE_SHA, "head_branch": "main"},
            },
            {
                "id": IGOR_ARTIFACT_ID,
                "name": f"igor-independent-ollama-evidence-{SOURCE_SHA}",
                "digest": IGOR_ARTIFACT_DIGEST,
                "size_in_bytes": 456,
                "expired": False,
                "workflow_run": {"id": flow_run_id, "head_sha": SOURCE_SHA, "head_branch": "main"},
            },
        ]
        result = resolve_artifact_bindings(
            {"total_count": 2, "artifacts": rows},
            source_sha=SOURCE_SHA,
            flow_run_id=flow_run_id,
        )
        self.assertEqual(AUTO_ARTIFACT_ID, result["auto"]["id"])
        self.assertEqual(AUTO_ARTIFACT_DIGEST, result["auto"]["digest"])
        self.assertEqual(IGOR_ARTIFACT_ID, result["igor"]["id"])
        self.assertEqual(IGOR_ARTIFACT_DIGEST, result["igor"]["digest"])

    def test_rejects_artifact_from_wrong_run(self):
        auto = {
            "id": AUTO_ARTIFACT_ID,
            "name": f"ola-auto-evidence-{SOURCE_SHA}",
            "digest": AUTO_ARTIFACT_DIGEST,
            "size_in_bytes": 123,
            "expired": False,
            "workflow_run": {"id": 1001, "head_sha": SOURCE_SHA, "head_branch": "main"},
        }
        igor = {
            "id": IGOR_ARTIFACT_ID,
            "name": f"igor-independent-ollama-evidence-{SOURCE_SHA}",
            "digest": IGOR_ARTIFACT_DIGEST,
            "size_in_bytes": 456,
            "expired": False,
            "workflow_run": {"id": 9999, "head_sha": SOURCE_SHA, "head_branch": "main"},
        }
        with self.assertRaisesRegex(ValueError, "different workflow run"):
            resolve_artifact_bindings(
                {"artifacts": [auto, igor]},
                source_sha=SOURCE_SHA,
                flow_run_id=1001,
            )

    def test_rejects_duplicate_artifact_names(self):
        auto = {
            "id": AUTO_ARTIFACT_ID,
            "name": f"ola-auto-evidence-{SOURCE_SHA}",
            "digest": AUTO_ARTIFACT_DIGEST,
            "size_in_bytes": 123,
            "expired": False,
            "workflow_run": {"id": 1001, "head_sha": SOURCE_SHA, "head_branch": "main"},
        }
        igor = {
            "id": IGOR_ARTIFACT_ID,
            "name": f"igor-independent-ollama-evidence-{SOURCE_SHA}",
            "digest": IGOR_ARTIFACT_DIGEST,
            "size_in_bytes": 456,
            "expired": False,
            "workflow_run": {"id": 1001, "head_sha": SOURCE_SHA, "head_branch": "main"},
        }
        with self.assertRaisesRegex(ValueError, "exactly one auto artifact"):
            resolve_artifact_bindings(
                {"artifacts": [auto, auto.copy(), igor]},
                source_sha=SOURCE_SHA,
                flow_run_id=1001,
            )



    def test_rejects_nested_igor_job_url_for_another_repository(self):
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
                    "html_url": "https://github.com/another-owner/another-repo/actions/runs/1001/job/2001",
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
            with self.assertRaisesRegex(ValueError, "not bound to the exact 12h flow run"):
                resolve_flow_run(
                    root / "required-runs.json",
                    root / "gate-status.json",
                    SOURCE_SHA,
                    REPOSITORY,
                )


    def test_verify_igor_bundle_rejects_duplicate_manifest_and_result_members(self):
        checksum_name = "evidence-bundle/integrity/bundle-files.sha256"

        def write_files(root: Path, files: dict[str, bytes]):
            checksum_lines = [
                f"{hashlib.sha256(payload).hexdigest()}  {name}"
                for name, payload in sorted(files.items())
                if name != checksum_name
            ]
            files[checksum_name] = ("\n".join(checksum_lines) + "\n").encode()
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                root_info = tarfile.TarInfo("evidence-bundle/")
                root_info.type = tarfile.DIRTYPE
                archive.addfile(root_info)
                for name, payload in files.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            bundle = root / "igor-ollama-evidence-bundle.tar.gz"
            bundle.write_bytes(buffer.getvalue())
            checksum = root / "igor-ollama-evidence-bundle.sha256"
            checksum.write_text(
                f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n",
                encoding="utf-8",
            )
            return bundle, checksum

        for target, key in (
            (
                "evidence-bundle/MANIFEST.json",
                f'"source_commit": "{SOURCE_SHA}"'.encode(),
            ),
            (
                "evidence-bundle/verification/igor-result.json",
                b'"status": "VERIFIED"',
            ),
        ):
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                root = Path(tmp)
                files = _bundle_files(SOURCE_SHA)
                self.assertIn(key, files[target])
                files[target] = files[target].replace(key, key + b", " + key, 1)
                bundle, checksum = write_files(root, files)

                with self.assertRaisesRegex(ValueError, "duplicate JSON member"):
                    verify_igor_bundle(bundle, checksum, SOURCE_SHA)


    def test_verify_auto_evidence_rejects_duplicate_json_members(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = (
                '{"schema":"ola-auto-evidence-v3",'
                f'"source_commit":"{SOURCE_SHA}",'
                f'"source_commit":"{SOURCE_SHA}",'
                '"trigger":"push","provider":"ollama",'
                '"status":"RUNTIME_CHAIN_VERIFIED",'
                '"verified_claim":true,"fail_closed":true,'
                '"preflight_artifact_integrity":"VERIFIED",'
                '"ollama_artifact_integrity":"VERIFIED",'
                '"independent_igor_artifact_integrity":"VERIFIED"}'
            ).encode("utf-8")
            (root / "ola-auto-evidence.json").write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            (root / "ola-auto-evidence.sha256").write_text(
                f"{digest}  ola-auto-evidence.json\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "duplicate JSON member"):
                verify_auto_evidence(root, SOURCE_SHA)



if __name__ == "__main__":
    unittest.main()
