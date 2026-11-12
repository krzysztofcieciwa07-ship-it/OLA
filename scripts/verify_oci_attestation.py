"""Verify a published OLA OCI image against its GitHub SLSA attestation.

This verifier deliberately accepts an image name without a tag and a full
sha256 manifest digest. GitHub CLI verifies the signed provenance, OIDC signer,
source repository, workflow identity, source ref and source commit. This module
then independently checks that the returned statement names the exact image
and digest requested by the caller.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_IMAGE_RE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+$")
_SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"


class VerificationError(RuntimeError):
    """Raised when GitHub cannot prove the requested image provenance."""


def _validate_inputs(
    image: str,
    digest: str,
    repository: str,
    signer_workflow: str,
    source_ref: str,
    source_sha: str,
) -> None:
    if not _IMAGE_RE.fullmatch(image):
        raise ValueError("image must be a tag-free GHCR name: ghcr.io/<owner>/<image>")
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("digest must be a lowercase sha256:<64-hex> OCI digest")
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use owner/repository form")
    expected_signer_prefix = f"{repository}/.github/workflows/"
    if not signer_workflow.startswith(expected_signer_prefix) or not signer_workflow.endswith((".yml", ".yaml")):
        raise ValueError("signer_workflow must identify a workflow in the source repository")
    if not source_ref.startswith("refs/heads/"):
        raise ValueError("source_ref must be a fully qualified branch ref")
    if not _GIT_SHA1_RE.fullmatch(source_sha):
        raise ValueError("source_sha must be a full 40-character Git commit SHA")


def _matching_verified_statement(
    payload: Any,
    *,
    image: str,
    digest: str,
) -> int:
    if not isinstance(payload, list):
        raise VerificationError("GitHub CLI returned a non-list attestation response")

    expected_hex = digest.removeprefix("sha256:")
    match_count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        verification_result = item.get("verificationResult")
        if not isinstance(verification_result, dict):
            continue
        statement = verification_result.get("statement")
        if not isinstance(statement, dict):
            continue
        if statement.get("predicateType") != _SLSA_PROVENANCE_V1:
            continue
        subjects = statement.get("subject")
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            if not isinstance(subject, dict) or subject.get("name") != image:
                continue
            subject_digest = subject.get("digest")
            if isinstance(subject_digest, dict) and subject_digest.get("sha256") == expected_hex:
                match_count += 1

    if match_count == 0:
        raise VerificationError("verified SLSA statement does not bind the exact image name and digest")
    return match_count


def verify_oci_attestation(
    image: str,
    digest: str,
    repository: str,
    signer_workflow: str,
    source_ref: str,
    source_sha: str,
) -> dict[str, Any]:
    """Cryptographically verify an OCI image and enforce its exact release binding."""
    _validate_inputs(image, digest, repository, signer_workflow, source_ref, source_sha)

    image_uri = f"oci://{image}@{digest}"
    command = [
        "gh",
        "attestation",
        "verify",
        image_uri,
        "--repo",
        repository,
        "--signer-workflow",
        signer_workflow,
        "--source-ref",
        source_ref,
        "--source-digest",
        source_sha,
        "--cert-oidc-issuer",
        _GITHUB_OIDC_ISSUER,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"could not run GitHub attestation verification: {exc}") from exc

    if completed.returncode != 0:
        reason = (completed.stderr or completed.stdout or "GitHub CLI verification failed").strip()
        raise VerificationError(reason)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("GitHub CLI returned invalid JSON after verification") from exc

    count = _matching_verified_statement(payload, image=image, digest=digest)
    return {
        "status": "VERIFIED",
        "image": image,
        "digest": digest,
        "image_ref": f"{image}@{digest}",
        "repository": repository,
        "signer_workflow": signer_workflow,
        "source_ref": source_ref,
        "source_sha": source_sha,
        "predicate_type": _SLSA_PROVENANCE_V1,
        "matching_verified_statements": count,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="tag-free GHCR image name")
    parser.add_argument("--digest", required=True, help="exact sha256 OCI manifest digest")
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    parser.add_argument("--signer-workflow", required=True, help="expected GitHub Actions signer workflow")
    parser.add_argument("--source-ref", required=True, help="expected fully qualified source branch ref")
    parser.add_argument("--source-sha", required=True, help="expected full Git source commit SHA")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_oci_attestation(
            image=args.image,
            digest=args.digest,
            repository=args.repository,
            signer_workflow=args.signer_workflow,
            source_ref=args.source_ref,
            source_sha=args.source_sha,
        )
    except (ValueError, VerificationError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
