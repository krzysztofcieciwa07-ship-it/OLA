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

from cryptography import x509
from cryptography.x509.oid import ObjectIdentifier

SCHEMA = "ola-github-oci-provenance/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_TRUST_ROOT_BYTES = 2 * 1024 * 1024
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\\Z")
RUN_INVOCATION_OID = ObjectIdentifier("1.3.6.1.4.1.57264.1.21")


class GitHubOCIProvenanceRejected(ValueError):
    """Raised when OCI provenance is missing, malformed, or fails policy."""


def _der_utf8_string(data: bytes) -> str:
    """Decode exactly one canonical DER UTF8String from a Fulcio extension."""
    if not isinstance(data, bytes) or len(data) < 2 or data[0] != 0x0C:
        raise ValueError("RUN_INVOCATION_EXTENSION_NOT_DER_UTF8STRING")
    length = data[1]
    position = 2
    if length & 0x80:
        count = length & 0x7F
        if not 1 <= count <= 4 or len(data) < position + count:
            raise ValueError("RUN_INVOCATION_DER_LENGTH_INVALID")
        encoded_length = data[position:position + count]
        if encoded_length[0] == 0:
            raise ValueError("RUN_INVOCATION_DER_LENGTH_NONCANONICAL")
        length = int.from_bytes(encoded_length, "big")
        if length < 128:
            raise ValueError("RUN_INVOCATION_DER_LENGTH_NONCANONICAL")
        position += count
    if length == 0 or position + length != len(data):
        raise ValueError("RUN_INVOCATION_DER_LENGTH_MISMATCH")
    try:
        return data[position:].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("RUN_INVOCATION_UTF8_INVALID") from exc


def _bundle_documents(bundle_bytes: bytes) -> list[dict]:
    try:
        decoded = bundle_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SIGSTORE_BUNDLE_UTF8_INVALID") from exc
    try:
        document = json.loads(decoded)
        if not isinstance(document, dict):
            raise ValueError("SIGSTORE_BUNDLE_OBJECT_REQUIRED")
        return [document]
    except json.JSONDecodeError:
        documents = []
        for line in decoded.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("SIGSTORE_BUNDLE_JSONL_OBJECT_REQUIRED")
            documents.append(item)
        if not documents:
            raise ValueError("SIGSTORE_BUNDLE_EMPTY")
        return documents


def _certificate_der(document: dict) -> bytes:
    material = document.get("verificationMaterial")
    if not isinstance(material, dict):
        raise ValueError("SIGSTORE_VERIFICATION_MATERIAL_MISSING")
    direct = material.get("certificate")
    direct_raw = direct.get("rawBytes") if isinstance(direct, dict) else None
    chain = material.get("x509CertificateChain")
    chain_raw = None
    if chain is not None:
        certificates = chain.get("certificates") if isinstance(chain, dict) else None
        if not isinstance(certificates, list) or not certificates or not isinstance(certificates[0], dict):
            raise ValueError("SIGSTORE_X509_CHAIN_INVALID")
        chain_raw = certificates[0].get("rawBytes")
    if direct_raw is not None and chain_raw is not None and direct_raw != chain_raw:
        raise ValueError("SIGSTORE_LEAF_CERTIFICATE_AMBIGUOUS")
    encoded = direct_raw if direct_raw is not None else chain_raw
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("SIGSTORE_SIGNING_CERTIFICATE_MISSING")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("SIGSTORE_SIGNING_CERTIFICATE_BASE64_INVALID") from exc


def verify_fulcio_run_invocation(
    bundle_bytes: bytes,
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
) -> bool:
    """Bind a Sigstore-verified bundle to one exact GitHub Actions run attempt.

    Call only after the GitHub CLI has cryptographically verified this same
    bundle and blob against the pinned Sigstore root, issuer and workflow.
    This helper parses the already-authenticated Fulcio leaf certificate.
    """
    if not isinstance(repository, str) or not REPOSITORY_PATTERN.fullmatch(repository):
        return False
    if type(run_id) is not int or run_id < 1 or type(run_attempt) is not int or run_attempt < 1:
        return False
    try:
        documents = _bundle_documents(bundle_bytes)
        expected = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
        for document in documents:
            certificate = x509.load_der_x509_certificate(_certificate_der(document))
            extension = certificate.extensions.get_extension_for_oid(RUN_INVOCATION_OID)
            if not isinstance(extension.value, x509.UnrecognizedExtension):
                return False
            if _der_utf8_string(extension.value.value) != expected:
                return False
        return bool(documents)
    except (ValueError, x509.ExtensionNotFound, json.JSONDecodeError):
        return False


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
    expected_trusted_root_sha256: str,
    expected_run_id: int,
    expected_run_attempt: int,
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
    if type(expected_run_id) is not int or expected_run_id < 1 or type(expected_run_attempt) is not int or expected_run_attempt < 1:
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
        or type(payload.get("run_id")) is not int
        or payload.get("run_id") != expected_run_id
        or type(payload.get("run_attempt")) is not int
        or payload.get("run_attempt") != expected_run_attempt
        or not isinstance(expected_trusted_root_sha256, str)
        or not HEX_64.fullmatch(expected_trusted_root_sha256)
        or payload.get("trusted_root_sha256") != expected_trusted_root_sha256
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
        try:
            json.loads(bundle.decode("utf-8"))
        except json.JSONDecodeError:
            bundle_lines = [line for line in bundle.splitlines() if line.strip()]
            if not bundle_lines:
                return False
            for line in bundle_lines:
                json.loads(line.decode("utf-8"))
        actual_root_sha256 = hashlib.sha256(trusted_root).hexdigest()
        if actual_root_sha256 != expected_trusted_root_sha256:
            return False
        if payload.get("bundle_sha256") != hashlib.sha256(bundle).hexdigest():
            return False
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
            "--deny-self-hosted-runners",
            "--source-digest", expected_source_sha,
            "--source-ref", expected_source_ref,
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
        if len(matching) != 1:
            return False
        # The CLI above verifies the very same bytes written to bundle_path.
        # Only then inspect Fulcio's signed Run Invocation URI extension.
        return verify_fulcio_run_invocation(
            bundle,
            repository=expected_repository,
            run_id=expected_run_id,
            run_attempt=expected_run_attempt,
        )


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
    expected_trusted_root_sha256: str,
    run_id: int,
    run_attempt: int,
    gh_binary: str = "gh",
) -> bytes:
    """Package actual build outputs only against an out-of-band trust-root pin."""
    if not isinstance(expected_trusted_root_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_trusted_root_sha256):
        raise GitHubOCIProvenanceRejected("TRUSTED_ROOT_PIN_MISSING_OR_INVALID")
    if type(run_id) is not int or run_id < 1 or type(run_attempt) is not int or run_attempt < 1:
        raise GitHubOCIProvenanceRejected("RUN_INVOCATION_IDENTITY_MISSING_OR_INVALID")
    try:
        bundle = bundle_path.read_bytes()
        trusted_root = trusted_root_path.read_bytes()
    except OSError as exc:
        raise GitHubOCIProvenanceRejected("ATTESTATION_MATERIAL_UNREADABLE") from exc
    actual_trusted_root_sha256 = hashlib.sha256(trusted_root).hexdigest()
    if actual_trusted_root_sha256 != expected_trusted_root_sha256:
        raise GitHubOCIProvenanceRejected("TRUSTED_ROOT_PIN_MISMATCH")
    payload = {
        "schema": SCHEMA,
        "repository": repository,
        "repository_id": str(repository_id),
        "source_sha": source_sha,
        "source_ref": source_ref,
        "workflow_identity": workflow_identity,
        "image_name": image_name,
        "image_digest": image_digest,
        "run_id": run_id,
        "run_attempt": run_attempt,
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
        expected_trusted_root_sha256=expected_trusted_root_sha256,
        expected_run_id=run_id,
        expected_run_attempt=run_attempt,
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
    expected_trusted_root_sha256: str,
    expected_run_id: int,
    expected_run_attempt: int,
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
            expected_trusted_root_sha256=expected_trusted_root_sha256,
            expected_run_id=expected_run_id,
            expected_run_attempt=expected_run_attempt,
            gh_binary=gh_binary,
        )
    return verify


class GitHubOCIProvenanceProvider:
    """Load and independently verify the provenance evidence for this runtime.

    The source SHA comes from the immutable image build-info file. The image
    digest and evidence file path are deployment-supplied immutable settings.
    Missing or mismatched material raises instead of returning provider claims.
    """

    def __init__(
        self,
        *,
        payload_path: Path,
        source_sha: str,
        image_digest: str,
        verifier: Callable[[bytes, str, str], bool],
    ):
        if not isinstance(payload_path, Path) or not payload_path.is_file():
            raise GitHubOCIProvenanceRejected("PROVENANCE_EVIDENCE_FILE_MISSING")
        if not isinstance(source_sha, str) or not HEX_40.fullmatch(source_sha):
            raise GitHubOCIProvenanceRejected("RUNTIME_SOURCE_SHA_INVALID")
        if not isinstance(image_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise GitHubOCIProvenanceRejected("RUNTIME_OCI_DIGEST_INVALID")
        if not callable(verifier):
            raise GitHubOCIProvenanceRejected("PROVENANCE_VERIFIER_NOT_CONFIGURED")
        self.payload_path = payload_path
        self.source_sha = source_sha
        self.image_digest = image_digest
        self.verifier = verifier

    def __call__(self, signing_input: dict) -> dict:
        if (
            not isinstance(signing_input, dict)
            or signing_input.get("source_commit") != self.source_sha
            or signing_input.get("image_digest") != self.image_digest
        ):
            raise GitHubOCIProvenanceRejected("EXECUTION_SOURCE_IMAGE_IDENTITY_MISMATCH")
        try:
            payload = self.payload_path.read_bytes()
        except OSError as exc:
            raise GitHubOCIProvenanceRejected("PROVENANCE_EVIDENCE_FILE_UNREADABLE") from exc
        if not self.verifier(payload, self.source_sha, self.image_digest):
            raise GitHubOCIProvenanceRejected("GITHUB_OCI_SLSA_VERIFICATION_FAILED")
        return {
            "json_bytes": payload,
            "verified": True,
            "source_sha": self.source_sha,
            "image_digest": self.image_digest,
        }


def github_oci_provenance_runtime_from_env() -> tuple[GitHubOCIProvenanceProvider, Callable[[bytes, str, str], bool]]:
    """Create the provenance provider/verifier pair from explicit deployment settings.

    Required environment variables:
      OLA_GITHUB_PROVENANCE_FILE
      OLA_OCI_IMAGE_DIGEST
      OLA_GITHUB_REPOSITORY
      OLA_GITHUB_REPOSITORY_ID
      OLA_GITHUB_WORKFLOW_IDENTITY
      OLA_SIGSTORE_TRUST_ROOT_SHA256

    The running source SHA is read from app.runtime_provenance; no caller-supplied
    source SHA is accepted. Private GHCR access requires a read-only Docker
    credential helper or DOCKER_CONFIG mounted into this process.
    """
    from app.runtime_provenance import runtime_build_invocation, runtime_source_commit

    required = {
        "OLA_GITHUB_PROVENANCE_FILE": os.environ.get("OLA_GITHUB_PROVENANCE_FILE"),
        "OLA_OCI_IMAGE_DIGEST": os.environ.get("OLA_OCI_IMAGE_DIGEST"),
        "OLA_GITHUB_REPOSITORY": os.environ.get("OLA_GITHUB_REPOSITORY"),
        "OLA_GITHUB_REPOSITORY_ID": os.environ.get("OLA_GITHUB_REPOSITORY_ID"),
        "OLA_GITHUB_WORKFLOW_IDENTITY": os.environ.get("OLA_GITHUB_WORKFLOW_IDENTITY"),
        "OLA_SIGSTORE_TRUST_ROOT_SHA256": os.environ.get("OLA_SIGSTORE_TRUST_ROOT_SHA256"),
    }
    missing = [key for key, value in required.items() if not isinstance(value, str) or not value]
    if missing:
        raise GitHubOCIProvenanceRejected("PROVENANCE_RUNTIME_CONFIG_MISSING:" + ",".join(missing))
    repository = required["OLA_GITHUB_REPOSITORY"]
    invocation = runtime_build_invocation()
    if invocation is None:
        raise GitHubOCIProvenanceRejected("RUNTIME_BUILD_RUN_INVOCATION_MISSING")
    run_id, run_attempt = invocation
    source_ref = os.environ.get("OLA_GITHUB_SOURCE_REF", "refs/heads/main")
    image_name = os.environ.get("OLA_GITHUB_IMAGE_NAME") or f"ghcr.io/{repository.lower()}"
    gh_binary = os.environ.get("OLA_GH_BINARY", "gh")
    verifier = github_oci_provenance_verifier(
        expected_repository=repository,
        expected_repository_id=required["OLA_GITHUB_REPOSITORY_ID"],
        expected_workflow_identity=required["OLA_GITHUB_WORKFLOW_IDENTITY"],
        expected_source_ref=source_ref,
        expected_image_name=image_name,
        expected_trusted_root_sha256=required["OLA_SIGSTORE_TRUST_ROOT_SHA256"],
        expected_run_id=run_id,
        expected_run_attempt=run_attempt,
        gh_binary=gh_binary,
    )
    source_sha = runtime_source_commit(require_build_info=True) or ""
    provider = GitHubOCIProvenanceProvider(
        payload_path=Path(required["OLA_GITHUB_PROVENANCE_FILE"]),
        source_sha=source_sha,
        image_digest=required["OLA_OCI_IMAGE_DIGEST"],
        verifier=verifier,
    )
    return provider, verifier
