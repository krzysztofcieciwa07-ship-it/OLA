"""Independent validation of nested NINA and IGOR evidence in the 12h aggregator."""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import re
import sqlite3
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

MAX_NESTED_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_NESTED_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_TAR_ENTRIES = 2000
MAX_TAR_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
EXPECTED_MODEL = "qwen2.5:0.5b-instruct"
EXPECTED_TASK = "Calculate 17 * 23 and return the exact verified result 391."

NINA_FILES = {
    "ollama-models.json", "nina-igor-ollama-proof.json",
    "nina-ollama-proof-context.json", "nina-ollama-evidence.sqlite3",
    "ola-nina-ollama-runtime.log", "provenance.txt", "ola-build-info.json",
    "runtime-image-revision.txt", "runtime-image-id.txt",
}
IGOR_BUNDLE_FILES = {
    "evidence-bundle/MANIFEST.json",
    "evidence-bundle/human/human-gate.json",
    "evidence-bundle/integrity/evidence-files.sha256",
    "evidence-bundle/integrity/nina-artifact-api-digest.txt",
    "evidence-bundle/provenance/provenance.txt",
    "evidence-bundle/runtime/nina-igor-ollama-proof.json",
    "evidence-bundle/runtime/nina-ollama-evidence.sqlite3",
    "evidence-bundle/runtime/nina-ollama-proof-context.json",
    "evidence-bundle/runtime/ollama-models.json",
    "evidence-bundle/runtime/ola-nina-ollama-runtime.log",
    "evidence-bundle/source/commit.txt",
    "evidence-bundle/source/ola-build-info.json",
    "evidence-bundle/source/runtime-image-id.txt",
    "evidence-bundle/source/runtime-image-revision.txt",
    "evidence-bundle/tamper/tamper-verifier.log",
    "evidence-bundle/verification/igor-result.json",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _key_values(path: Path) -> dict[str, str] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    result: dict[str, str] = {}
    for line in lines:
        if not line or "=" not in line:
            return None
        key, value = line.split("=", 1)
        if not key or key in result:
            return None
        result[key] = value
    return result


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify_sha256_manifest(base: Path, manifest: Path, expected: set[str]) -> tuple[bool, str]:
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False, "nested_checksum_manifest_missing"
    if not lines or len(lines) != len(expected):
        return False, "nested_checksum_manifest_invalid"
    seen: set[str] = set()
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            return False, "nested_checksum_manifest_invalid"
        supplied, name = line[:64].lower(), line[66:]
        path = PurePosixPath(name)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", supplied)
            or not name or "\\" in name or path.is_absolute() or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or ":" in path.parts[0] or name in seen
        ):
            return False, "nested_checksum_manifest_unsafe_path"
        candidate = base.joinpath(*path.parts)
        if candidate.is_symlink() or not candidate.is_file():
            return False, "nested_checksum_manifest_file_missing"
        try:
            actual = _digest(candidate)
        except OSError:
            return False, "nested_checksum_manifest_file_unreadable"
        if not hmac.compare_digest(actual, supplied):
            return False, "nested_checksum_manifest_digest_mismatch"
        seen.add(name)
    if seen != expected:
        return False, "nested_checksum_manifest_coverage_mismatch"
    return True, "verified"


def verify_mapped_sha256_manifest(
    manifest: Path,
    files_by_name: dict[str, Path],
    expected: set[str],
) -> tuple[bool, str]:
    """Verify a source manifest when an evidence bundle relocates named files."""
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False, "nested_checksum_manifest_missing"
    if not lines or len(lines) != len(expected) or set(files_by_name) != expected:
        return False, "nested_checksum_manifest_invalid"

    seen: set[str] = set()
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            return False, "nested_checksum_manifest_invalid"
        supplied, name = line[:64].lower(), line[66:]
        path = PurePosixPath(name)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", supplied)
            or not name or "\\" in name or path.is_absolute() or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or ":" in path.parts[0] or name in seen or name not in expected
        ):
            return False, "nested_checksum_manifest_unsafe_path"
        candidate = files_by_name[name]
        if candidate.is_symlink() or not candidate.is_file():
            return False, "nested_checksum_manifest_file_missing"
        try:
            actual = _digest(candidate)
        except OSError:
            return False, "nested_checksum_manifest_file_unreadable"
        if not hmac.compare_digest(actual, supplied):
            return False, "nested_checksum_manifest_digest_mismatch"
        seen.add(name)
    if seen != expected:
        return False, "nested_checksum_manifest_coverage_mismatch"
    return True, "verified"


def _tree(root: Path) -> dict[str, str] | None:
    if not root.is_dir() or root.is_symlink():
        return None
    result: dict[str, str] = {}
    try:
        for path in root.rglob("*"):
            if path.is_symlink():
                return None
            if path.is_file():
                result[path.relative_to(root).as_posix()] = _digest(path)
            elif not path.is_dir():
                return None
    except OSError:
        return None
    return result


def same_file_tree(left: Path, right: Path) -> bool:
    a, b = _tree(left), _tree(right)
    return a is not None and b is not None and a == b


def verify_nested_artifact_copies(
    repository: str,
    artifacts: list[dict[str, Any]],
    aggregator_root: Path,
    source_sha: str,
    temporary_root: Path,
    download_archive: Callable[..., tuple[bool, str]],
) -> tuple[bool, str, dict[str, dict[str, Any]]]:
    """Verify original preflight/NINA/IGOR archives by API digest and exact file-tree match."""
    specs = (
        ("preflight", f"ola-preflight-evidence-{source_sha}", "downloaded/preflight"),
        ("nina", f"nina-igor-ollama-full-flow-{source_sha}", "downloaded/ollama"),
        ("igor", f"igor-independent-ollama-evidence-{source_sha}", "downloaded/independent-igor"),
    )
    total = 0
    verified: dict[str, dict[str, Any]] = {}
    for label, name, relative in specs:
        matches = [item for item in artifacts if item.get("name") == name]
        if len(matches) != 1:
            return False, f"{label}_artifact_missing_or_ambiguous", {}
        artifact = matches[0]
        artifact_id, digest, size = artifact.get("id"), artifact.get("digest"), artifact.get("size_in_bytes")
        if (
            type(artifact_id) is not int or artifact.get("expired") is not False
            or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or type(size) is not int or not 1 <= size <= MAX_NESTED_ARTIFACT_BYTES
        ):
            return False, f"{label}_artifact_metadata_invalid", {}
        total += size
        if total > MAX_TOTAL_NESTED_ARTIFACT_BYTES:
            return False, "nested_artifact_total_size_limit", {}
        target = temporary_root / f"original-{label}" / "extracted"
        ok, reason = download_archive(repository, artifact_id, digest, size, target)
        if not ok:
            return False, f"{label}_{reason}", {}
        if not same_file_tree(target, aggregator_root / relative):
            return False, f"{label}_artifact_copy_mismatch", {}
        verified[label] = {"id": artifact_id, "name": name, "digest": digest, "size_in_bytes": size}
    return True, "verified", verified


class _TarUncompressedLimitExceeded(Exception):
    """Raised when the decompressed TAR stream crosses its byte budget."""


class _BoundedReader:
    """Bound decompressed reads, including TAR headers and padding."""

    def __init__(self, stream: Any, limit: int):
        self._stream = stream
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        remaining = self._limit - self._read
        requested = remaining + 1 if size is None or size < 0 else min(size, remaining + 1)
        data = self._stream.read(requested)
        if len(data) > remaining:
            raise _TarUncompressedLimitExceeded
        self._read += len(data)
        return data


def _verify_tar(tar_path: Path, bundle: Path) -> tuple[bool, str]:
    try:
        actual: dict[str, str] = {}
        seen: set[str] = set()
        total_member_bytes = 0
        with gzip.open(tar_path, "rb") as compressed:
            bounded = _BoundedReader(compressed, MAX_TAR_UNCOMPRESSED_BYTES)
            with tarfile.open(fileobj=bounded, mode="r|") as archive:
                for member in archive:
                    if len(seen) >= MAX_TAR_ENTRIES:
                        return False, "igor_tar_entry_limit"
                    name = member.name.rstrip("/")
                    path = PurePosixPath(name)
                    if (
                        not name or "\\" in name or path.is_absolute() or not path.parts
                        or any(part in {"", ".", ".."} for part in path.parts)
                        or ":" in path.parts[0] or name in seen
                    ):
                        return False, "igor_tar_unsafe_path"
                    seen.add(name)
                    if member.isdir():
                        continue
                    if not member.isfile() or member.size > 128 * 1024 * 1024:
                        return False, "igor_tar_unsafe_entry"
                    total_member_bytes += member.size
                    if total_member_bytes > MAX_TAR_UNCOMPRESSED_BYTES:
                        return False, "igor_tar_size_limit"
                    stream = archive.extractfile(member)
                    if stream is None:
                        return False, "igor_tar_member_unreadable"
                    digest = hashlib.sha256()
                    remaining = member.size
                    while remaining:
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            return False, "igor_tar_member_truncated"
                        digest.update(chunk)
                        remaining -= len(chunk)
                    if stream.read(1):
                        return False, "igor_tar_member_size_mismatch"
                    actual[name] = digest.hexdigest()
                if not seen:
                    return False, "igor_tar_entry_limit"
    except _TarUncompressedLimitExceeded:
        return False, "igor_tar_size_limit"
    except (OSError, EOFError, gzip.BadGzipFile, tarfile.TarError, ValueError):
        return False, "igor_tar_invalid"

    expected: dict[str, str] = {}
    try:
        for path in bundle.rglob("*"):
            if path.is_symlink():
                return False, "igor_bundle_symlink"
            if path.is_file():
                expected[f"{bundle.name}/{path.relative_to(bundle).as_posix()}"] = _digest(path)
    except OSError:
        return False, "igor_bundle_unreadable"
    return (True, "verified") if actual == expected else (False, "igor_tar_bundle_mismatch")


def verify_nested_evidence(
    root: Path,
    source_sha: str,
    expected_run_id: int | None,
    expected_nina_artifact_digest: str | None,
) -> tuple[bool, str]:
    preflight = root / "downloaded" / "preflight"
    nina = root / "downloaded" / "ollama"
    igor = root / "downloaded" / "independent-igor"
    bundle = igor / "evidence-bundle"
    required = (
        preflight / "source-provenance.txt", preflight / "nina-gate.log",
        preflight / "igor-replay-gate.log", nina / "evidence-files.sha256",
        nina / "nina-igor-ollama-proof.json", nina / "nina-ollama-proof-context.json",
        nina / "nina-ollama-evidence.sqlite3", nina / "provenance.txt",
        nina / "runtime-image-revision.txt", nina / "runtime-image-id.txt",
        nina / "ola-build-info.json", nina / "ollama-models.json",
        nina / "ola-nina-ollama-runtime.log", igor / "igor-ollama-evidence-bundle.tar.gz",
        igor / "igor-ollama-evidence-bundle.sha256", bundle / "MANIFEST.json",
        bundle / "human/human-gate.json", bundle / "integrity/bundle-files.sha256",
        bundle / "integrity/evidence-files.sha256", bundle / "integrity/nina-artifact-api-digest.txt",
        bundle / "provenance/provenance.txt", bundle / "runtime/nina-igor-ollama-proof.json",
        bundle / "runtime/nina-ollama-evidence.sqlite3",
        bundle / "runtime/nina-ollama-proof-context.json", bundle / "source/commit.txt",
        bundle / "source/ola-build-info.json", bundle / "source/runtime-image-id.txt",
        bundle / "source/runtime-image-revision.txt", bundle / "tamper/tamper-verifier.log",
        bundle / "verification/igor-result.json",
    )
    if any(not p.is_file() or p.is_symlink() or p.stat().st_size == 0 for p in required):
        return False, "nested_evidence_missing"
    if type(expected_run_id) is not int or expected_run_id < 1:
        return False, "nested_evidence_expected_run_id_missing"
    if not isinstance(expected_nina_artifact_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_nina_artifact_digest):
        return False, "nested_evidence_expected_nina_digest_invalid"

    checks = (
        (nina, nina / "evidence-files.sha256", NINA_FILES),
        (igor, bundle / "integrity/bundle-files.sha256", IGOR_BUNDLE_FILES),
        (igor, igor / "igor-ollama-evidence-bundle.sha256", {"igor-ollama-evidence-bundle.tar.gz"}),
    )
    for base, manifest, expected in checks:
        ok, reason = verify_sha256_manifest(base, manifest, expected)
        if not ok:
            return False, reason

    # IGOR preserves the NINA payload in runtime/, while source/build and
    # provenance metadata are deliberately stored in their dedicated folders.
    # Verify the original NINA manifest against this explicit path map.
    bundle_nina_paths = {
        "ollama-models.json": bundle / "runtime/ollama-models.json",
        "nina-igor-ollama-proof.json": bundle / "runtime/nina-igor-ollama-proof.json",
        "nina-ollama-proof-context.json": bundle / "runtime/nina-ollama-proof-context.json",
        "nina-ollama-evidence.sqlite3": bundle / "runtime/nina-ollama-evidence.sqlite3",
        "ola-nina-ollama-runtime.log": bundle / "runtime/ola-nina-ollama-runtime.log",
        "provenance.txt": bundle / "provenance/provenance.txt",
        "ola-build-info.json": bundle / "source/ola-build-info.json",
        "runtime-image-revision.txt": bundle / "source/runtime-image-revision.txt",
        "runtime-image-id.txt": bundle / "source/runtime-image-id.txt",
    }
    ok, reason = verify_mapped_sha256_manifest(
        bundle / "integrity/evidence-files.sha256",
        bundle_nina_paths,
        NINA_FILES,
    )
    if not ok:
        return False, reason
    ok, reason = _verify_tar(igor / "igor-ollama-evidence-bundle.tar.gz", bundle)
    if not ok:
        return False, reason

    source_provenance = _key_values(preflight / "source-provenance.txt")
    if (
        source_provenance is None or source_provenance.get("SOURCE_COMMIT") != source_sha
        or source_provenance.get("SOURCE_BRANCH") != "main"
        or source_provenance.get("TRIGGER") not in {"schedule", "workflow_dispatch", "push"}
    ):
        return False, "preflight_source_provenance_mismatch"
    for path in (preflight / "nina-gate.log", preflight / "igor-replay-gate.log"):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False, "preflight_log_unreadable"
        if "[100%]" not in content or "FAILED" in content:
            return False, "preflight_test_log_not_successful"

    proof = _json(nina / "nina-igor-ollama-proof.json")
    context = _json(nina / "nina-ollama-proof-context.json")
    provenance = _key_values(nina / "provenance.txt")
    build = _json(nina / "ola-build-info.json")
    if proof is None or context is None or provenance is None or build is None:
        return False, "nina_evidence_invalid"
    status_fields = proof.get("status_fields")
    run_id, tenant_id = context.get("run_id"), context.get("tenant_id")
    if (
        not isinstance(status_fields, dict)
        or proof.get("commit") != source_sha or proof.get("provider") != "ollama"
        or proof.get("model") != EXPECTED_MODEL or proof.get("llm_invocations") != 6
        or proof.get("status") != "REVIEW" or proof.get("nina_status") != "VERIFIED"
        or proof.get("igor_status") != "VERIFIED" or proof.get("provenance_status") != "VERIFIED"
        or proof.get("replay_status") != "VERIFIED" or proof.get("policy_status") != "VERIFIED"
        or proof.get("human_gate_status") != "BLOCK"
        or proof.get("flow") != ["NINA", "REAL_OLLAMA_LLM", "IGOR", "PROVENANCE", "REPLAY", "HUMAN_GATE"]
        or not isinstance(run_id, str) or not run_id or not isinstance(tenant_id, str) or not tenant_id
        or proof.get("run_id") != run_id or proof.get("tenant_id") != tenant_id
        or context.get("task") != EXPECTED_TASK
        or status_fields.get("HUMAN_GATE") != "REVIEW"
        or status_fields.get("EXECUTION_ALLOWED") != "REVIEW"
    ):
        return False, "nina_proof_source_or_status_mismatch"
    if (
        provenance.get("commit") != source_sha or provenance.get("run") != str(expected_run_id)
        or provenance.get("tenant_id") != tenant_id or provenance.get("run_id") != run_id
        or provenance.get("provider") != "ollama" or provenance.get("model") != EXPECTED_MODEL
        or build.get("source_commit") != source_sha
    ):
        return False, "nina_provenance_mismatch"
    try:
        revision = (nina / "runtime-image-revision.txt").read_text(encoding="utf-8").strip()
        image_id = (nina / "runtime-image-id.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return False, "nina_runtime_metadata_missing"
    if revision != source_sha or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        return False, "nina_runtime_metadata_mismatch"
    models = _json(nina / "ollama-models.json")
    if models is None or EXPECTED_MODEL not in json.dumps(models, sort_keys=True):
        return False, "nina_model_inventory_mismatch"

    try:
        db = sqlite3.connect(f"file:{nina / 'nina-ollama-evidence.sqlite3'}?mode=ro", uri=True)
        integrity = db.execute("PRAGMA integrity_check").fetchone()
        table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence_records'").fetchone()
        count = db.execute("SELECT COUNT(*) FROM evidence_records").fetchone() if table else None
        tenants = db.execute("SELECT DISTINCT tenant_id FROM evidence_records").fetchall() if table else []
        db.close()
    except sqlite3.Error:
        return False, "nina_evidence_database_invalid"
    if integrity is None or integrity[0] != "ok" or count is None or count[0] < 6 or tenants != [(tenant_id,)]:
        return False, "nina_evidence_database_integrity_mismatch"

    manifest = _json(bundle / "MANIFEST.json")
    result = _json(bundle / "verification/igor-result.json")
    human = _json(bundle / "human/human-gate.json")
    tamper = _json(bundle / "tamper/tamper-verifier.log")
    igor_provenance = _key_values(bundle / "provenance/provenance.txt")
    igor_build = _json(bundle / "source/ola-build-info.json")
    if any(value is None for value in (manifest, result, human, tamper, igor_provenance, igor_build)):
        return False, "igor_evidence_invalid"
    if (
        manifest.get("schema") != "ola-igor-evidence/v1"
        or manifest.get("source_commit") != source_sha or manifest.get("nina_run_id") != expected_run_id
        or manifest.get("run_id") != run_id or manifest.get("tenant_id") != tenant_id
        or manifest.get("provider") != "ollama" or manifest.get("model") != EXPECTED_MODEL
        or manifest.get("igor") != "VERIFIED" or manifest.get("tamper") != "BLOCK"
        or manifest.get("human_gate") != "PENDING"
        or result.get("source_commit") != source_sha or result.get("nina_run_id") != expected_run_id
        or result.get("nina_artifact_name") != f"nina-igor-ollama-full-flow-{source_sha}"
        or result.get("status") != "VERIFIED" or result.get("hash_chain") != "VERIFIED"
        or result.get("evidence_count") != 6 or result.get("replay") != "VERIFIED"
        or result.get("tamper") != "BLOCK" or result.get("human_gate") != "PENDING"
        or result.get("provider") != "ollama" or result.get("model") != EXPECTED_MODEL
        or human.get("status") != "PENDING" or tamper.get("status") != "BLOCK"
        or igor_provenance.get("commit") != source_sha
        or igor_provenance.get("run") != str(expected_run_id)
        or igor_provenance.get("tenant_id") != tenant_id or igor_provenance.get("run_id") != run_id
        or igor_provenance.get("provider") != "ollama" or igor_provenance.get("model") != EXPECTED_MODEL
        or igor_build.get("source_commit") != source_sha
    ):
        return False, "igor_verifier_or_provenance_mismatch"

    try:
        api_digest = (bundle / "integrity/nina-artifact-api-digest.txt").read_text(encoding="utf-8").strip()
        source_commit = (bundle / "source/commit.txt").read_text(encoding="utf-8").strip()
        source_revision = (bundle / "source/runtime-image-revision.txt").read_text(encoding="utf-8").strip()
        source_image_id = (bundle / "source/runtime-image-id.txt").read_text(encoding="utf-8").strip()
        nina_manifest = (nina / "evidence-files.sha256").read_bytes()
        igor_manifest = (bundle / "integrity/evidence-files.sha256").read_bytes()
        same_files = all(
            (nina / name).read_bytes() == bundle_nina_paths[name].read_bytes()
            for name in NINA_FILES
        )
    except OSError:
        return False, "igor_nested_runtime_files_missing"
    if (
        api_digest != expected_nina_artifact_digest or source_commit != source_sha
        or source_revision != source_sha or source_image_id != image_id
        or nina_manifest != igor_manifest or not same_files
    ):
        return False, "igor_nested_nina_copy_mismatch"
    return True, "verified"
