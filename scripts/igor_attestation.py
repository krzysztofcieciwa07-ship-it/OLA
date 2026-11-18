#!/usr/bin/env python3
"""Prepare and verify main-only Sigstore attestations for IGOR evidence bundles."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path, PurePosixPath
from typing import Any

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
_PREDICATE_TYPE = "https://ola-di-os.dev/attestation/igor-evidence/v1"
_FINAL_WORKFLOW_PATH = ".github/workflows/final-production-gate.yml"
_FINAL_WORKFLOW_NAME = "OLA FINAL PRODUCTION GATE"
_FINAL_WORKFLOW_REF = "refs/heads/main"
_FLOW_WORKFLOW_PATH = ".github/workflows/ola-12h-autoflow.yml"
_FLOW_WORKFLOW_NAME = "OLA 12h Autonomous Evidence Flow"
_FLOW_GATE_NAME = "OLA 12h Autonomous Evidence Flow"
_IGOR_GATE_NAME = "IGOR Independent Ollama Evidence Gate"
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_CHECKSUM_FILE_BYTES = 4096
_MAX_AUTO_SUMMARY_BYTES = 4 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
# Bound the complete decompressed TAR stream, including PAX/GNU extension
# headers, member headers, padding and end markers. Regular-file limits alone
# do not constrain attacker-controlled extension metadata.
_MAX_TAR_STREAM_BYTES = _MAX_TOTAL_BYTES + 16 * 1024 * 1024
_MAX_MEMBERS = 1024
_ARTIFACT_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON members instead of accepting parser-dependent values."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _require_sha1(value: str) -> None:
    if not isinstance(value, str) or not _SHA1.fullmatch(value):
        raise ValueError("source SHA must be 40 lowercase hexadecimal characters")


def _require_sha256(value: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError("SHA-256 digest must be 64 lowercase hexadecimal characters")


def _require_repository(value: str) -> None:
    if not isinstance(value, str) or not _REPOSITORY.fullmatch(value):
        raise ValueError("repository must be an exact owner/name value")


def _require_run_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_artifact_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ARTIFACT_DIGEST.fullmatch(value):
        raise ValueError(f"{label} must be a GitHub sha256 artifact digest")
    return value


def _read_checksum(path: Path, expected_name: str) -> str:
    with path.open("rb") as stream:
        raw = stream.read(_MAX_CHECKSUM_FILE_BYTES + 1)
    if len(raw) > _MAX_CHECKSUM_FILE_BYTES:
        raise ValueError(f"{path.name} exceeds the checksum-file size limit")
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"{path.name} must contain exactly one checksum line")
    match = re.fullmatch(r"([0-9a-f]{64})  (.+)", lines[0])
    if not match or match.group(2) != expected_name:
        raise ValueError(f"{path.name} does not bind the expected subject filename")
    return match.group(1)


def _validate_tar_name(name: str, is_directory: bool) -> str:
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise ValueError("IGOR bundle contains an unsafe archive path")
    normalized = name[:-1] if name.endswith("/") else name
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("IGOR bundle contains a path traversal or ambiguous path")
    if parts[0] != "evidence-bundle":
        raise ValueError("IGOR bundle contains a file outside evidence-bundle/")
    if len(parts) == 1 and not is_directory:
        raise ValueError("evidence-bundle root must be a directory")
    return normalized


class _TarStreamLimitExceeded(Exception):
    """Raised when decompressed TAR bytes exceed the archive-wide budget."""


class _BoundedReader:
    """Limit bytes read from the decompressed TAR stream, including headers."""

    def __init__(self, stream: Any, limit: int):
        self._stream = stream
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        remaining = self._limit - self._read
        requested = remaining + 1 if size is None or size < 0 else min(size, remaining + 1)
        data = self._stream.read(requested)
        if len(data) > remaining:
            raise _TarStreamLimitExceeded
        self._read += len(data)
        return data


def _read_tar_files(bundle_bytes: bytes) -> dict[str, bytes]:
    if not bundle_bytes or len(bundle_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError("IGOR bundle archive is empty or exceeds the compressed-size limit")
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    total_size = 0
    try:
        # Stream decompression through a hard byte budget. Using r:gz/getmembers()
        # first materializes PAX extension records before member-size checks and
        # therefore permits highly-compressible metadata bombs.
        with gzip.GzipFile(fileobj=io.BytesIO(bundle_bytes), mode="rb") as compressed:
            bounded = _BoundedReader(compressed, _MAX_TAR_STREAM_BYTES)
            with tarfile.open(fileobj=bounded, mode="r|") as archive:
                for member in archive:
                    if len(seen) >= _MAX_MEMBERS:
                        raise ValueError("IGOR bundle member count is outside the allowed range")
                    normalized = _validate_tar_name(member.name, member.isdir())
                    if normalized in seen:
                        raise ValueError("IGOR bundle contains duplicate archive paths")
                    seen.add(normalized)
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("IGOR bundle contains a link or non-regular archive member")
                    if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
                        raise ValueError("IGOR bundle member exceeds the size limit")
                    total_size += member.size
                    if total_size > _MAX_TOTAL_BYTES:
                        raise ValueError("IGOR bundle exceeds the total uncompressed-size limit")
                    if getattr(member, "sparse", None):
                        raise ValueError("IGOR bundle contains a sparse archive member")
                    if any(key in {"linkpath", "GNU.sparse.map", "GNU.sparse.size"} for key in member.pax_headers):
                        raise ValueError("IGOR bundle contains extended link or sparse archive metadata")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError("IGOR bundle member could not be read")
                    payload = stream.read(_MAX_MEMBER_BYTES + 1)
                    if len(payload) != member.size:
                        raise ValueError("IGOR bundle member size does not match its archive header")
                    files[normalized] = payload
    except _TarStreamLimitExceeded as exc:
        raise ValueError("IGOR bundle exceeds the decompressed TAR stream limit") from exc
    except (tarfile.TarError, gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ValueError(f"IGOR bundle is not a valid gzip tar archive: {exc}") from exc
    return files


def verify_igor_bundle(bundle_path: Path, checksum_path: Path, source_sha: str) -> dict[str, Any]:
    """Verify the outer checksum, safe archive layout, inner file hashes and IGOR claims."""
    _require_sha1(source_sha)
    # Never read an artifact archive into memory before enforcing its compressed
    # byte budget. The TAR parser applies a second, decompressed-stream limit.
    with bundle_path.open("rb") as stream:
        bundle_bytes = stream.read(_MAX_ARCHIVE_BYTES + 1)
    if not bundle_bytes or len(bundle_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError("IGOR bundle archive is empty or exceeds the compressed-size limit")
    expected_bundle_sha = _read_checksum(checksum_path, bundle_path.name)
    actual_bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    if actual_bundle_sha != expected_bundle_sha:
        raise ValueError("IGOR bundle SHA-256 does not match its checksum file")

    files = _read_tar_files(bundle_bytes)
    checksum_name = "evidence-bundle/integrity/bundle-files.sha256"
    manifest_name = "evidence-bundle/MANIFEST.json"
    result_name = "evidence-bundle/verification/igor-result.json"
    commit_name = "evidence-bundle/source/commit.txt"
    for required in (checksum_name, manifest_name, result_name, commit_name):
        if required not in files:
            raise ValueError(f"IGOR bundle is missing {required}")

    checksum_text = files[checksum_name].decode("utf-8")
    listed: dict[str, str] = {}
    for line in checksum_text.splitlines():
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("IGOR internal checksum manifest has an invalid line")
        digest, name = match.groups()
        if name == checksum_name or name in listed or name not in files:
            raise ValueError("IGOR internal checksum manifest contains an invalid path")
        if not name.startswith("evidence-bundle/"):
            raise ValueError("IGOR internal checksum manifest escapes its bundle root")
        listed[name] = digest
    expected_files = set(files) - {checksum_name}
    if set(listed) != expected_files:
        raise ValueError("IGOR internal checksum manifest does not cover every bundle file")
    for name, expected_digest in listed.items():
        if hashlib.sha256(files[name]).hexdigest() != expected_digest:
            raise ValueError(f"IGOR internal checksum mismatch: {name}")

    try:
        manifest = json.loads(files[manifest_name], object_pairs_hook=_unique_object)
        result = json.loads(files[result_name], object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("IGOR manifest or result is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or not isinstance(result, dict):
        raise ValueError("IGOR manifest and result must be JSON objects")
    if files[commit_name].decode("utf-8").strip() != source_sha:
        raise ValueError("IGOR source/commit.txt does not match the exact source SHA")
    if manifest.get("schema") != "ola-igor-evidence/v1":
        raise ValueError("IGOR manifest schema is not supported")
    if manifest.get("source_commit") != source_sha or result.get("source_commit") != source_sha:
        raise ValueError("IGOR manifest/result source SHA mismatch")
    if manifest.get("igor") != "VERIFIED" or result.get("status") != "VERIFIED":
        raise ValueError("IGOR independent verification is not VERIFIED")
    if result.get("verifier") != "IGOR":
        raise ValueError("IGOR result does not identify the independent verifier")
    if manifest.get("tamper") != "BLOCK" or result.get("tamper") != "BLOCK":
        raise ValueError("IGOR tamper mutation did not produce BLOCK")
    if result.get("hash_chain") != "VERIFIED" or result.get("replay") != "VERIFIED":
        raise ValueError("IGOR hash-chain or replay verification is incomplete")
    if manifest.get("human_gate") != "PENDING" or result.get("human_gate") != "PENDING":
        raise ValueError("IGOR evidence must retain the pending Human Gate")
    if manifest.get("provider") != "ollama" or result.get("provider") != "ollama":
        raise ValueError("IGOR evidence provider is not the dedicated Ollama lane")
    if not isinstance(manifest.get("model"), str) or not manifest["model"]:
        raise ValueError("IGOR manifest model is missing")
    if result.get("model") != manifest["model"] or result.get("evidence_count") != 6:
        raise ValueError("IGOR model or evidence count does not match the verified bundle")
    if manifest.get("nina_run_id") != result.get("nina_run_id"):
        raise ValueError("IGOR manifest and result NINA run IDs differ")
    if not manifest.get("tenant_id") or not manifest.get("run_id") or not result.get("nina_artifact_name"):
        raise ValueError("IGOR tenant, run or NINA artifact binding is missing")

    return {
        "bundle_sha256": actual_bundle_sha,
        "manifest_sha256": hashlib.sha256(files[manifest_name]).hexdigest(),
        "result_sha256": hashlib.sha256(files[result_name]).hexdigest(),
        "provider": "ollama",
        "model": manifest["model"],
        "evidence_count": result["evidence_count"],
        "status": "VERIFIED",
        "hash_chain": "VERIFIED",
        "tamper": "BLOCK",
        "replay": "VERIFIED",
        "human_gate": "PENDING",
    }


def verify_auto_evidence(auto_dir: Path, source_sha: str) -> str:
    summary_path = auto_dir / "ola-auto-evidence.json"
    checksum_path = auto_dir / "ola-auto-evidence.sha256"
    if not summary_path.is_file() or not checksum_path.is_file():
        raise ValueError("exact-SHA AUTO evidence summary or checksum is missing")
    expected = _read_checksum(checksum_path, summary_path.name)
    with summary_path.open("rb") as stream:
        raw = stream.read(_MAX_AUTO_SUMMARY_BYTES + 1)
    if not raw or len(raw) > _MAX_AUTO_SUMMARY_BYTES:
        raise ValueError("AUTO evidence summary is empty or exceeds the size limit")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError("AUTO evidence summary SHA-256 mismatch")
    try:
        summary = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("AUTO evidence summary is not valid JSON") from exc
    if not isinstance(summary, dict):
        raise ValueError("AUTO evidence summary must be a JSON object")
    if summary.get("schema") != "ola-auto-evidence-v3":
        raise ValueError("AUTO evidence summary schema is not supported")
    if summary.get("source_commit") != source_sha or summary.get("trigger") != "push":
        raise ValueError("AUTO evidence summary is not bound to the exact main push SHA")
    if summary.get("provider") != "ollama" or summary.get("status") != "RUNTIME_CHAIN_VERIFIED":
        raise ValueError("AUTO evidence does not prove the required Ollama runtime chain")
    if summary.get("verified_claim") is not True or summary.get("fail_closed") is not True:
        raise ValueError("AUTO evidence claim is not fail-closed and verified")
    for key in (
        "preflight_artifact_integrity",
        "ollama_artifact_integrity",
        "independent_igor_artifact_integrity",
    ):
        if summary.get(key) != "VERIFIED":
            raise ValueError(f"AUTO evidence component is not VERIFIED: {key}")
    return actual


def resolve_flow_run(
    required_runs_path: Path,
    gate_status_path: Path,
    source_sha: str,
    repository: str,
) -> int:
    """Bind the 12h artifact to the exact successful main push and nested IGOR job."""
    _require_sha1(source_sha)
    _require_repository(repository)
    try:
        required = json.loads(required_runs_path.read_text(encoding="utf-8"))
        gate_status = json.loads(gate_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"required run evidence is unreadable: {exc}") from exc
    exact = gate_status.get("exact_source_gates") if isinstance(gate_status, dict) else None
    if not isinstance(exact, dict):
        raise ValueError("final gate status has no exact-source gate map")
    flow = exact.get(_FLOW_GATE_NAME)
    igor = exact.get(_IGOR_GATE_NAME)
    if not isinstance(flow, dict) or not isinstance(igor, dict):
        raise ValueError("final gate status is missing the 12h flow or independent IGOR job")
    if flow.get("head_sha") != source_sha or flow.get("status") != "completed" or flow.get("conclusion") != "success":
        raise ValueError("12h flow is not a successful exact-source run")
    if flow.get("event") != "push" or flow.get("path") != _FLOW_WORKFLOW_PATH:
        raise ValueError("12h flow identity is not the canonical main-push workflow")
    if igor.get("head_sha") != source_sha or igor.get("status") != "completed" or igor.get("conclusion") != "success":
        raise ValueError("independent IGOR nested job is not successful on the exact source SHA")
    flow_id = _require_run_id(flow.get("id"), "12h flow run ID")
    workflow_id = _require_run_id(flow.get("workflow_id"), "12h workflow ID")
    runs = required.get("workflow_runs") if isinstance(required, dict) else None
    if not isinstance(runs, list):
        raise ValueError("required-runs evidence does not contain a workflow_runs list")
    matches = [run for run in runs if isinstance(run, dict) and run.get("id") == flow_id]
    if len(matches) != 1:
        raise ValueError("exact 12h flow run ID is absent or duplicated in required-runs evidence")
    run = matches[0]
    expected = {
        "name": _FLOW_WORKFLOW_NAME,
        "path": _FLOW_WORKFLOW_PATH,
        "head_sha": source_sha,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "workflow_id": workflow_id,
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise ValueError(f"12h flow run identity mismatch for {key}")
    igor_job_id = _require_run_id(igor.get("id"), "IGOR nested job ID")
    job_url = igor.get("html_url")
    try:
        parsed_job_url = urlsplit(job_url) if isinstance(job_url, str) else None
    except ValueError as exc:
        raise ValueError("IGOR nested job URL is invalid") from exc
    expected_job_path = f"/{repository}/actions/runs/{flow_id}/job/{igor_job_id}"
    if (
        parsed_job_url is None
        or parsed_job_url.scheme != "https"
        or parsed_job_url.netloc != "github.com"
        or parsed_job_url.path != expected_job_path
        or parsed_job_url.query
        or parsed_job_url.fragment
    ):
        raise ValueError("IGOR nested job is not bound to the exact 12h flow run")
    return flow_id


def resolve_artifact_bindings(artifact_data: Any, *, source_sha: str, flow_run_id: int) -> dict[str, dict[str, Any]]:
    """Resolve immutable AUTO and IGOR artifact identities from one exact main run."""
    _require_sha1(source_sha)
    _require_run_id(flow_run_id, "12h flow run ID")
    artifacts = artifact_data.get("artifacts") if isinstance(artifact_data, dict) else None
    if not isinstance(artifacts, list):
        raise ValueError("GitHub artifact API response has no artifacts list")
    names = {
        "auto": f"ola-auto-evidence-{source_sha}",
        "igor": f"igor-independent-ollama-evidence-{source_sha}",
    }
    resolved: dict[str, dict[str, Any]] = {}
    for label, expected_name in names.items():
        matches = [x for x in artifacts if isinstance(x, dict) and x.get("name") == expected_name]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {label} artifact named {expected_name}")
        artifact = matches[0]
        if artifact.get("expired") is not False:
            raise ValueError(f"{label} artifact is expired or has no explicit unexpired status")
        run = artifact.get("workflow_run")
        if not isinstance(run, dict) or run.get("id") != flow_run_id:
            raise ValueError(f"{label} artifact belongs to a different workflow run")
        if run.get("head_sha") != source_sha or run.get("head_branch") != "main":
            raise ValueError(f"{label} artifact is not bound to the exact main source SHA")
        artifact_id = _require_run_id(artifact.get("id"), f"{label} artifact ID")
        digest = _require_artifact_digest(artifact.get("digest"), f"{label} artifact digest")
        size = artifact.get("size_in_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"{label} artifact has an invalid size")
        resolved[label] = {"id": artifact_id, "name": expected_name, "digest": digest, "size_in_bytes": size}
    if resolved["auto"]["id"] == resolved["igor"]["id"]:
        raise ValueError("AUTO and IGOR artifact IDs must be distinct")
    return resolved


def fetch_artifact_bindings(repository: str, flow_run_id: int, source_sha: str) -> dict[str, dict[str, Any]]:
    _require_repository(repository)
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise ValueError("GH_TOKEN is required to resolve exact workflow artifact metadata")
    url = f"https://api.github.com/repos/{repository}/actions/runs/{flow_run_id}/artifacts?per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    return resolve_artifact_bindings(payload, source_sha=source_sha, flow_run_id=flow_run_id)


def build_predicate(
    *,
    source_sha: str,
    repository: str,
    final_run_id: int,
    flow_run_id: int,
    auto_evidence_sha256: str,
    bundle_info: dict[str, Any],
) -> dict[str, Any]:
    _require_sha1(source_sha)
    _require_repository(repository)
    _require_run_id(final_run_id, "final gate run ID")
    _require_run_id(flow_run_id, "12h flow run ID")
    _require_sha256(auto_evidence_sha256)
    _require_sha256(bundle_info.get("bundle_sha256"))
    _require_sha256(bundle_info.get("manifest_sha256"))
    _require_sha256(bundle_info.get("result_sha256"))
    igor_id = _require_run_id(bundle_info.get("igor_artifact_id"), "IGOR artifact ID")
    auto_id = _require_run_id(bundle_info.get("auto_artifact_id"), "AUTO artifact ID")
    igor_digest = _require_artifact_digest(bundle_info.get("igor_artifact_digest"), "IGOR artifact digest")
    auto_digest = _require_artifact_digest(bundle_info.get("auto_artifact_digest"), "AUTO artifact digest")
    igor_name = f"igor-independent-ollama-evidence-{source_sha}"
    auto_name = f"ola-auto-evidence-{source_sha}"
    if bundle_info.get("igor_artifact_name") != igor_name or bundle_info.get("auto_artifact_name") != auto_name:
        raise ValueError("producer artifact names are not bound to the exact source SHA")
    if igor_id == auto_id:
        raise ValueError("AUTO and IGOR artifact IDs must be distinct")
    return {
        "schema": _PREDICATE_TYPE,
        "source": {"repository": repository, "commit": source_sha},
        "workflow": {
            "path": _FINAL_WORKFLOW_PATH,
            "ref": _FINAL_WORKFLOW_REF,
            "trigger": "push",
            "run_id": final_run_id,
        },
        "producer": {
            "workflow_path": _FLOW_WORKFLOW_PATH,
            "run_id": flow_run_id,
            "auto_artifact": {"id": auto_id, "name": auto_name, "archive_digest": auto_digest},
            "igor_artifact": {"id": igor_id, "name": igor_name, "archive_digest": igor_digest},
        },
        "evidence": {
            "bundle_sha256": bundle_info["bundle_sha256"],
            "manifest_sha256": bundle_info["manifest_sha256"],
            "result_sha256": bundle_info["result_sha256"],
            "auto_evidence_sha256": auto_evidence_sha256,
            "status": "VERIFIED",
            "hash_chain": "VERIFIED",
            "tamper": "BLOCK",
            "replay": "VERIFIED",
            "human_gate": "PENDING",
            "provider": "ollama",
            "model": bundle_info["model"],
            "evidence_count": 6,
        },
    }


def verify_attestation_data(
    data: Any,
    *,
    expected_source_sha: str,
    expected_repository: str,
    expected_flow_run_id: int,
    expected_final_run_id: int,
    expected_subject_sha256: str,
    expected_igor_artifact_id: int,
    expected_igor_artifact_digest: str,
    expected_auto_artifact_id: int,
    expected_auto_artifact_digest: str,
    expected_workflow_path: str = _FINAL_WORKFLOW_PATH,
    expected_workflow_ref: str = _FINAL_WORKFLOW_REF,
    expected_workflow_name: str = _FINAL_WORKFLOW_NAME,
) -> dict[str, Any]:
    _require_sha1(expected_source_sha)
    _require_repository(expected_repository)
    _require_run_id(expected_flow_run_id, "expected 12h flow run ID")
    _require_run_id(expected_final_run_id, "expected final gate run ID")
    _require_sha256(expected_subject_sha256)
    _require_run_id(expected_igor_artifact_id, "expected IGOR artifact ID")
    _require_run_id(expected_auto_artifact_id, "expected AUTO artifact ID")
    _require_artifact_digest(expected_igor_artifact_digest, "expected IGOR artifact digest")
    _require_artifact_digest(expected_auto_artifact_digest, "expected AUTO artifact digest")
    if expected_workflow_path != _FINAL_WORKFLOW_PATH or expected_workflow_ref != _FINAL_WORKFLOW_REF:
        raise ValueError("IGOR attestation verification is restricted to the canonical main workflow")
    if expected_workflow_name != _FINAL_WORKFLOW_NAME:
        raise ValueError("IGOR attestation workflow name is not canonical")
    if not isinstance(data, list):
        raise ValueError("gh attestation verify output must be a JSON list")

    repository_uri = f"https://github.com/{expected_repository}"
    signer_uri = f"{repository_uri}/{expected_workflow_path}@{expected_workflow_ref}"
    for item in data:
        if not isinstance(item, dict):
            continue
        verification = item.get("verificationResult")
        if not isinstance(verification, dict):
            continue
        identity = verification.get("verifiedIdentity")
        timestamps = verification.get("verifiedTimestamps")
        signature = verification.get("signature")
        certificate = signature.get("certificate") if isinstance(signature, dict) else None
        statement = verification.get("statement")
        if not isinstance(identity, dict) or identity.get("subjectAlternativeName") != signer_uri:
            continue
        if not isinstance(timestamps, list) or not timestamps:
            continue
        if not isinstance(certificate, dict) or not isinstance(statement, dict):
            continue
        certificate_fields = {
            "sourceRepositoryDigest": expected_source_sha,
            "sourceRepositoryURI": repository_uri,
            "sourceRepositoryRef": expected_workflow_ref,
            "githubWorkflowSHA": expected_source_sha,
            "githubWorkflowRepository": expected_repository,
            "githubWorkflowRef": expected_workflow_ref,
            "githubWorkflowTrigger": "push",
            "githubWorkflowName": expected_workflow_name,
            "buildSignerURI": signer_uri,
            "buildConfigURI": signer_uri,
        }
        if any(certificate.get(key) != value for key, value in certificate_fields.items()):
            continue
        if statement.get("_type") != _STATEMENT_TYPE or statement.get("predicateType") != _PREDICATE_TYPE:
            continue
        subjects = statement.get("subject")
        if not isinstance(subjects, list):
            continue
        digests = {
            subject.get("digest", {}).get("sha256")
            for subject in subjects
            if isinstance(subject, dict) and isinstance(subject.get("digest"), dict)
        }
        if expected_subject_sha256 not in digests:
            continue
        predicate = statement.get("predicate")
        if not isinstance(predicate, dict) or predicate.get("schema") != _PREDICATE_TYPE:
            continue
        source = predicate.get("source")
        workflow = predicate.get("workflow")
        producer = predicate.get("producer")
        evidence = predicate.get("evidence")
        if not all(isinstance(value, dict) for value in (source, workflow, producer, evidence)):
            continue
        if source != {"repository": expected_repository, "commit": expected_source_sha}:
            continue
        if workflow != {
            "path": expected_workflow_path,
            "ref": expected_workflow_ref,
            "trigger": "push",
            "run_id": expected_final_run_id,
        }:
            continue
        if producer != {
            "workflow_path": _FLOW_WORKFLOW_PATH,
            "run_id": expected_flow_run_id,
            "auto_artifact": {
                "id": expected_auto_artifact_id,
                "name": f"ola-auto-evidence-{expected_source_sha}",
                "archive_digest": expected_auto_artifact_digest,
            },
            "igor_artifact": {
                "id": expected_igor_artifact_id,
                "name": f"igor-independent-ollama-evidence-{expected_source_sha}",
                "archive_digest": expected_igor_artifact_digest,
            },
        }:
            continue
        if evidence.get("bundle_sha256") != expected_subject_sha256:
            continue
        if evidence.get("status") != "VERIFIED" or evidence.get("hash_chain") != "VERIFIED":
            continue
        if evidence.get("tamper") != "BLOCK" or evidence.get("replay") != "VERIFIED":
            continue
        if evidence.get("human_gate") != "PENDING" or evidence.get("provider") != "ollama":
            continue
        if evidence.get("evidence_count") != 6 or not isinstance(evidence.get("model"), str) or not evidence["model"]:
            continue
        try:
            _require_sha256(evidence.get("manifest_sha256"))
            _require_sha256(evidence.get("result_sha256"))
            _require_sha256(evidence.get("auto_evidence_sha256"))
        except ValueError:
            continue
        return {
            "status": "VERIFIED",
            "source_sha": expected_source_sha,
            "repository": expected_repository,
            "workflow_path": expected_workflow_path,
            "workflow_ref": expected_workflow_ref,
            "final_run_id": expected_final_run_id,
            "flow_run_id": expected_flow_run_id,
            "subject_sha256": expected_subject_sha256,
            "predicate_type": _PREDICATE_TYPE,
            "human_gate": "PENDING",
        }
    raise ValueError("no Sigstore attestation binds the exact main source, run identities and IGOR bundle")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _append_output(path: str | None, values: dict[str, Any]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise ValueError("GitHub output values must be scalar strings or integers")
            text = str(value)
            if "\n" in text or "\r" in text:
                raise ValueError("GitHub output value contains a newline")
            stream.write(f"{key}={text}\n")


def _prepare(args: argparse.Namespace) -> int:
    _require_sha1(args.source_sha)
    _require_repository(args.repository)
    flow_run_id = resolve_flow_run(
        Path(args.required_runs),
        Path(args.gate_status),
        args.source_sha,
        args.repository,
    )
    artifact_bindings = fetch_artifact_bindings(args.repository, flow_run_id, args.source_sha)
    if args.resolve_only:
        binding = {
            "source_sha": args.source_sha,
            "flow_run_id": flow_run_id,
            "workflow_path": _FLOW_WORKFLOW_PATH,
            "artifacts": artifact_bindings,
        }
        _write_json(Path(args.output), binding)
        _append_output(args.github_output, {
            "flow_run_id": flow_run_id,
            "auto_artifact_id": artifact_bindings["auto"]["id"],
            "auto_artifact_digest": artifact_bindings["auto"]["digest"],
            "igor_artifact_id": artifact_bindings["igor"]["id"],
            "igor_artifact_digest": artifact_bindings["igor"]["digest"],
        })
        print(json.dumps(binding, sort_keys=True))
        return 0
    if args.flow_run_id != flow_run_id:
        raise ValueError("downloaded 12h flow run ID differs from the final-gate run binding")
    final_run_id = _require_run_id(args.final_run_id, "final gate run ID")
    expected_outputs = {
        "auto_artifact_id": artifact_bindings["auto"]["id"],
        "auto_artifact_digest": artifact_bindings["auto"]["digest"],
        "igor_artifact_id": artifact_bindings["igor"]["id"],
        "igor_artifact_digest": artifact_bindings["igor"]["digest"],
    }
    supplied_outputs = {
        "auto_artifact_id": args.auto_artifact_id,
        "auto_artifact_digest": args.auto_artifact_digest,
        "igor_artifact_id": args.igor_artifact_id,
        "igor_artifact_digest": args.igor_artifact_digest,
    }
    if supplied_outputs != expected_outputs:
        raise ValueError("artifact metadata changed between resolution and exact-ID download")
    auto_dir = Path(args.auto_evidence_dir)
    auto_digest = verify_auto_evidence(auto_dir, args.source_sha)
    independent = auto_dir / "downloaded" / "independent-igor"
    bundle_path = independent / "igor-ollama-evidence-bundle.tar.gz"
    checksum_path = independent / "igor-ollama-evidence-bundle.sha256"
    bundle_info = verify_igor_bundle(bundle_path, checksum_path, args.source_sha)
    igor_name = f"igor-independent-ollama-evidence-{args.source_sha}"
    original_dir = Path(args.original_igor_artifact_dir) / igor_name
    original_bundle = original_dir / "igor-ollama-evidence-bundle.tar.gz"
    original_checksum = original_dir / "igor-ollama-evidence-bundle.sha256"
    original_info = verify_igor_bundle(original_bundle, original_checksum, args.source_sha)
    if original_info != bundle_info:
        raise ValueError("IGOR bundle copied into AUTO artifact differs from the exact-ID IGOR artifact")
    bundle_info.update({
        "auto_artifact_id": artifact_bindings["auto"]["id"],
        "auto_artifact_name": artifact_bindings["auto"]["name"],
        "auto_artifact_digest": artifact_bindings["auto"]["digest"],
        "igor_artifact_id": artifact_bindings["igor"]["id"],
        "igor_artifact_name": artifact_bindings["igor"]["name"],
        "igor_artifact_digest": artifact_bindings["igor"]["digest"],
    })
    predicate = build_predicate(
        source_sha=args.source_sha,
        repository=args.repository,
        final_run_id=final_run_id,
        flow_run_id=flow_run_id,
        auto_evidence_sha256=auto_digest,
        bundle_info=bundle_info,
    )
    _write_json(Path(args.output), predicate)
    _append_output(
        args.github_output,
        {
            "bundle_sha256": bundle_info["bundle_sha256"],
            "manifest_sha256": bundle_info["manifest_sha256"],
            "result_sha256": bundle_info["result_sha256"],
        },
    )
    print(json.dumps({"status": "PREPARED", **predicate["evidence"]}, sort_keys=True))
    return 0


def _verify(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.attestation).read_text(encoding="utf-8"))
    subject_sha = hashlib.sha256(Path(args.subject).read_bytes()).hexdigest()
    result = verify_attestation_data(
        data,
        expected_source_sha=args.expected_source_sha,
        expected_repository=args.expected_repository,
        expected_flow_run_id=args.expected_flow_run_id,
        expected_final_run_id=args.expected_final_run_id,
        expected_subject_sha256=subject_sha,
        expected_igor_artifact_id=args.expected_igor_artifact_id,
        expected_igor_artifact_digest=args.expected_igor_artifact_digest,
        expected_auto_artifact_id=args.expected_auto_artifact_id,
        expected_auto_artifact_digest=args.expected_auto_artifact_digest,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="resolve the exact flow run or prepare the IGOR predicate")
    prepare.add_argument("--source-sha", required=True)
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--required-runs", required=True)
    prepare.add_argument("--gate-status", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--github-output")
    prepare.add_argument("--resolve-only", action="store_true")
    prepare.add_argument("--flow-run-id", type=int)
    prepare.add_argument("--final-run-id", type=int)
    prepare.add_argument("--auto-evidence-dir")
    prepare.add_argument("--original-igor-artifact-dir")
    prepare.add_argument("--auto-artifact-id", type=int)
    prepare.add_argument("--auto-artifact-digest")
    prepare.add_argument("--igor-artifact-id", type=int)
    prepare.add_argument("--igor-artifact-digest")
    verify = subparsers.add_parser("verify", help="verify gh attestation verify output and exact source bindings")
    verify.add_argument("--attestation", required=True)
    verify.add_argument("--subject", required=True)
    verify.add_argument("--expected-source-sha", required=True)
    verify.add_argument("--expected-repository", required=True)
    verify.add_argument("--expected-flow-run-id", required=True, type=int)
    verify.add_argument("--expected-final-run-id", required=True, type=int)
    verify.add_argument("--expected-igor-artifact-id", required=True, type=int)
    verify.add_argument("--expected-igor-artifact-digest", required=True)
    verify.add_argument("--expected-auto-artifact-id", required=True, type=int)
    verify.add_argument("--expected-auto-artifact-digest", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            return _prepare(args)
        if args.command == "verify":
            return _verify(args)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError, tarfile.TarError) as exc:
        print(f"IGOR_ATTESTATION=BLOCK reason={exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
