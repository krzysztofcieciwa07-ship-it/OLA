#!/usr/bin/env python3
"""Fail-closed verifier for source-bound SLSA provenance attestations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SLSA_PREDICATE = "https://slsa.dev/provenance/v1"
_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
_DEFAULT_WORKFLOW_NAME = "OLA Supply Chain Evidence Gate"
_ALLOWED_TRIGGERS = {"push", "schedule", "workflow_dispatch"}


def _valid_workflow_path(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(".github/workflows/")
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and value.endswith((".yml", ".yaml"))
    )


def verify_attestation_data(
    data: Any,
    *,
    expected_source_sha: str,
    expected_repository: str,
    expected_workflow_path: str,
    expected_workflow_ref: str,
    expected_subject_sha256: str,
    expected_workflow_name: str = _DEFAULT_WORKFLOW_NAME,
) -> dict[str, str]:
    """Verify the attested image subject and all source/workflow identity bindings."""
    if not isinstance(expected_source_sha, str) or not _SHA1.fullmatch(expected_source_sha):
        raise ValueError("expected source SHA must be a 40-character lowercase hex digest")
    if not isinstance(expected_subject_sha256, str) or not _SHA256.fullmatch(expected_subject_sha256):
        raise ValueError("expected subject SHA-256 must be a 64-character lowercase hex digest")
    if not isinstance(expected_repository, str) or not expected_repository.strip():
        raise ValueError("expected repository is required")
    if not _valid_workflow_path(expected_workflow_path):
        raise ValueError("expected workflow path is invalid")
    if expected_workflow_ref != "refs/heads/main":
        raise ValueError("supply-chain attestation verification is restricted to refs/heads/main")
    if not isinstance(expected_workflow_name, str) or not expected_workflow_name.strip():
        raise ValueError("expected workflow name is required")
    if not isinstance(data, list):
        raise ValueError("attestation verification result must be a list")

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
        if not isinstance(identity, dict) or not identity:
            continue
        if not isinstance(timestamps, list) or not timestamps:
            continue
        if not isinstance(certificate, dict) or not isinstance(statement, dict):
            continue

        if certificate.get("sourceRepositoryDigest") != expected_source_sha:
            continue
        if certificate.get("sourceRepositoryURI") != repository_uri:
            continue
        if certificate.get("sourceRepositoryRef") != expected_workflow_ref:
            continue
        if certificate.get("githubWorkflowSHA") != expected_source_sha:
            continue
        if certificate.get("githubWorkflowRepository") != expected_repository:
            continue
        if certificate.get("githubWorkflowRef") != expected_workflow_ref:
            continue
        if certificate.get("githubWorkflowTrigger") not in _ALLOWED_TRIGGERS:
            continue
        if certificate.get("githubWorkflowName") != expected_workflow_name:
            continue
        if certificate.get("buildSignerURI") != signer_uri:
            continue
        if certificate.get("buildConfigURI") != signer_uri:
            continue

        if statement.get("_type") != _STATEMENT_TYPE:
            continue
        if statement.get("predicateType") != _SLSA_PREDICATE:
            continue
        subjects = statement.get("subject")
        if not isinstance(subjects, list):
            continue
        subject_digests = {
            subject.get("digest", {}).get("sha256")
            for subject in subjects
            if isinstance(subject, dict) and isinstance(subject.get("digest"), dict)
        }
        if expected_subject_sha256 not in subject_digests:
            continue

        predicate = statement.get("predicate")
        build_definition = predicate.get("buildDefinition") if isinstance(predicate, dict) else None
        external = build_definition.get("externalParameters") if isinstance(build_definition, dict) else None
        workflow = external.get("workflow") if isinstance(external, dict) else None
        if not isinstance(workflow, dict):
            continue
        if workflow.get("path") != expected_workflow_path:
            continue
        if workflow.get("ref") != expected_workflow_ref:
            continue
        if workflow.get("repository") != repository_uri:
            continue

        dependencies = build_definition.get("resolvedDependencies")
        if not isinstance(dependencies, list):
            continue
        if not any(
            isinstance(dependency, dict)
            and isinstance(dependency.get("digest"), dict)
            and dependency["digest"].get("gitCommit") == expected_source_sha
            for dependency in dependencies
        ):
            continue

        trigger = certificate["githubWorkflowTrigger"]
        return {
            "status": "VERIFIED",
            "source_sha": expected_source_sha,
            "subject_sha256": expected_subject_sha256,
            "workflow_name": expected_workflow_name,
            "workflow_path": expected_workflow_path,
            "workflow_ref": expected_workflow_ref,
            "trigger": trigger,
            "predicate_type": _SLSA_PREDICATE,
        }

    raise ValueError("no verified SLSA attestation binds the exact main source SHA and image subject")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-workflow-path", required=True)
    parser.add_argument("--expected-workflow-ref", required=True)
    args = parser.parse_args(argv)

    try:
        data = json.loads(Path(args.attestation).read_text(encoding="utf-8"))
        subject_sha256 = hashlib.sha256(Path(args.subject).read_bytes()).hexdigest()
        result = verify_attestation_data(
            data,
            expected_source_sha=args.expected_source_sha,
            expected_repository=args.expected_repository,
            expected_workflow_path=args.expected_workflow_path,
            expected_workflow_ref=args.expected_workflow_ref,
            expected_subject_sha256=subject_sha256,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"SUPPLY_CHAIN_ATTESTATION=FAIL reason={exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
