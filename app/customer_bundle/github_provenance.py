"""Independent verifier for GitHub SLSA OCI attestations.

The payload carries the exact Sigstore bundle and GitHub/Sigstore trusted root.
Verification delegates cryptographic Sigstore and in-toto validation to the
GitHub CLI, then applies OLA's immutable repository/workflow/source/image policy.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

SCHEMA = "ola-github-oci-provenance/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_TRUST_ROOT_BYTES = 2 * 1024 * 1024
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class GitHubOCIProvenanceRejected(ValueError):
    """Raised when OCI provenance is missing, malformed, or fails policy."""


def _decode_material(value: object, *, label: str, limit: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise GitHubOCIProvenanceRejected(f"{label}_MISSING")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GitHubOCIProvenanceRejected(f"{label}_BASE64_INVALID") from exc
    if not raw or len(raw) > limit:
        raise GitHubOCIProvenanceRejected(f"{label}_SIZE_INVALID")
    return raw


def _statement_matches(
    result: object,
    *,
    repository: str,
    repository_id: str,
    source_sha: str,
    source_ref: str,
    image_name: str,
    image_digest: str,
) -> bool:
    if not isinstance(result, dict):
        return False
    verification = result.get("verificationResult")
    if not isinstance(verification, dict):
        return False
    certificate = (verification.get("signature") or {}).get("certificate")
    statement = verification.get("statement")
    if not isinstance(certificate, dict) or not isinstance(statement, dict):
        return False

    # These certificate fields are derived from GitHub's OIDC certificate,
    # not from the workflow-controlled SLSA predicate.
    if str(certificate.get("sourceRepositoryIdentifier", "")) != repository_id:
        return False
    if certificate.get("issuer") not in (None, OIDC_ISSUER):
        return False

    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        return False
    if not any(
        isinstance(item, dict)
        and item.get("name") == image_name
        and isinstance(item.get("digest"), dict)
        and item["digest"].get("sha256") == image_digest.removeprefix("sha256:")
        for item in subjects
    ):
        return False
    if statement.get("_type") != "https://in-toto.io/Statement/v1":
        return False
    if statement.get("predicateType") != PREDICATE_TYPE:
        return False

    predicate = statement.get("predicate")
    build = predicate.get("buildDefinition") if isinstance(predicate, dict) else None
    dependencies = build.get("resolvedDependencies") if isinstance(build, dict) else None
    if not isinstance(dependencies, list):
        return False
    expected_uri = f"git+https://github.com/{repository}@{source_ref}"
    return any(
        isinstance(item, dict)
        and item.get("uri") == expected_uri
        and isinstance(item.get("digest"), dict)
        and item["digest"].get("gitCommit") == source_sha
        for item in dependencies
    )


def verify_github_oci_provenance(
    payload_bytes: bytes,
    expected_source_sha: str,
    expected_image_digest: str,
    *,
    expected_repository: str,
    expected_repository_id: str,
    expected_workflow_identity: str,
    expected_source_ref: str = "refs/heads/main",
    expected_image_name: str | None = None,
    gh_binary: str = "gh",
    timeout_seconds: int = 90,
) -> bool:
    """Verify a packaged Sigstore bundle against a pinned GitHub trust policy.

    Uses the local bundle and local trusted-root file (never GitHub's
    attestations API). The OCI registry reference is used to bind the verified
    statement to the named image digest; registry access may be required.
    """
    if not isinstance(payload_bytes, bytes) or not payload_bytes or len(payload_bytes) > MAX_BUNDLE_BYTES + MAX_TRUST_ROOT_BYTES + 65536:
        return False
    if not isinstance(expected_source_sha, str) or not HEX_40.fullmatch(expected_source_sha):
        return False
    if not isinstance(expected_image_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_image_digest):
        return False
    if not all(isinstance(value, str) and value for value in (
        expected_repository, expected_repository_id, expected_workflow_identity,
        expected_source_ref, gh_binary,
    )):
        return False
    image_name = expected_image_name or f"ghcr.io/{expected_repository.lower()}"
    if not image_name.startswith("ghcr.io/") or "@" in image_name or ":" in image_name.split("/", 1)[-1]:
        return False
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return False
    if (
        payload.get("repository") != expected_repository
        or str(payload.get("repository_id", "")) != expected_repository_id
        or payload.get("source_sha") != expected_source_sha
        or payload.get("source_ref") != expected_source_ref
        or payload.get("workflow_identity") != expected_workflow_identity
        or payload.get("image_name") != image_name
        or payload.get("image_digest") != expected_image_digest
    ):
        return False

    try:
        bundle = _decode_material(
            payload.get("attestation_bundle_b64"),
            label="ATTESTATION_BUNDLE",
            limit=MAX_BUNDLE_BYTES,
        )
        trusted_root = _decode_material(
            payload.get("trusted_root_b64"),
            label="TRUSTED_ROOT",
            limit=MAX_TRUST_ROOT_BYTES,
        )
        # GitHub trusted-root output is JSON Lines. Reject empty/garbled roots
        # before invoking the verifier; the CLI validates the trust semantics.
        root_lines = [line for line in trusted_root.splitlines() if line.strip()]
        if not root_lines or any(not line.lstrip().startswith(b"{") for line in root_lines):
            return False
        json.loads(bundle.decode("utf-8"))
        for line in root_lines:
            json.loads(line.decode("utf-8"))
    except (GitHubOCIProvenanceRejected, UnicodeDecodeError, json.JSONDecodeError):
        return False

    with tempfile.TemporaryDirectory(prefix="ola-gh-provenance-") as temporary:
        root = Path(temporary)
        bundle_path = root / "attestation.bundle.json"
        trust_path = root / "trusted_root.jsonl"
        bundle_path.write_bytes(bundle)
        trust_path.write_bytes(trusted_root)
        command = [
            gh_binary, "attestation", "verify",
            f"oci://{image_name}@{expected_image_digest}",
            "--repo", expected_repository,
            "--bundle", str(bundle_path),
            "--custom-trusted-root", str(trust_path),
            "--cert-identity", expected_workflow_identity,
            "--cert-oidc-issuer", OIDC_ISSUER,
            "--predicate-type", PREDICATE_TYPE,
            "--format", "json",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False,
                timeout=timeout_seconds, env=os.environ.copy(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
        try:
            verified = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(verified, list) or not verified:
            return False
        matching = [
            item for item in verified
            if _statement_matches(
                item,
                repository=expected_repository,
                repository_id=expected_repository_id,
                source_sha=expected_source_sha,
                source_ref=expected_source_ref,
                image_name=image_name,
                image_digest=expected_image_digest,
            )
        ]
        return len(matching) == 1


def create_github_oci_provenance_payload(
    *,
    bundle_path: Path,
    trusted_root_path: Path,
    repository: str,
    repository_id: str,
    source_sha: str,
    source_ref: str,
    workflow_identity: str,
    image_name: str,
    image_digest: str,
    gh_binary: str = "gh",
) -> bytes:
    """Package and verify actual build outputs for later independent checks."""
    try:
        bundle = bundle_path.read_bytes()
        trusted_root = trusted_root_path.read_bytes()
    except OSError as exc:
        raise GitHubOCIProvenanceRejected("ATTESTATION_MATERIAL_UNREADABLE") from exc
    payload = {
        "schema": SCHEMA,
        "repository": repository,
        "repository_id": str(repository_id),
        "source_sha": source_sha,
        "source_ref": source_ref,
        "workflow_identity": workflow_identity,
        "image_name": image_name,
        "image_digest": image_digest,
        "attestation_bundle_b64": base64.b64encode(bundle).decode("ascii"),
        "trusted_root_b64": base64.b64encode(trusted_root).decode("ascii"),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "trusted_root_sha256": hashlib.sha256(trusted_root).hexdigest(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not verify_github_oci_provenance(
        encoded, source_sha, image_digest,
        expected_repository=repository,
        expected_repository_id=str(repository_id),
        expected_workflow_identity=workflow_identity,
        expected_source_ref=source_ref,
        expected_image_name=image_name,
        gh_binary=gh_binary,
    ):
        raise GitHubOCIProvenanceRejected("GITHUB_OCI_SLSA_VERIFICATION_FAILED")
    return encoded


def github_oci_provenance_verifier(
    *,
    expected_repository: str,
    expected_repository_id: str,
    expected_workflow_identity: str,
    expected_source_ref: str = "refs/heads/main",
    expected_image_name: str | None = None,
    gh_binary: str = "gh",
) -> Callable[[bytes, str, str], bool]:
    """Return the callback required by verify_customer_bundle()."""
    def verify(payload: bytes, source_sha: str, image_digest: str) -> bool:
        return verify_github_oci_provenance(
            payload, source_sha, image_digest,
            expected_repository=expected_repository,
            expected_repository_id=expected_repository_id,
            expected_workflow_identity=expected_workflow_identity,
            expected_source_ref=expected_source_ref,
            expected_image_name=expected_image_name,
            gh_binary=gh_binary,
        )
    return verify
