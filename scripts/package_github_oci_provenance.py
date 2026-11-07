#!/usr/bin/env python3
"""Package actual GitHub Sigstore bundle and trusted root after policy verification."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from app.customer_bundle.github_provenance import (
    GitHubOCIProvenanceRejected,
    create_github_oci_provenance_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--trusted-root", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--workflow-identity", required=True)
    parser.add_argument("--image-name", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gh-binary", default="gh")
    args = parser.parse_args()

    try:
        payload = create_github_oci_provenance_payload(
            bundle_path=args.bundle,
            trusted_root_path=args.trusted_root,
            repository=args.repository,
            repository_id=args.repository_id,
            source_sha=args.source_sha,
            source_ref=args.source_ref,
            workflow_identity=args.workflow_identity,
            image_name=args.image_name,
            image_digest=args.image_digest,
            gh_binary=args.gh_binary,
        )
        args.output.write_bytes(payload)
    except (OSError, GitHubOCIProvenanceRejected) as exc:
        print(f"PROVENANCE_PACKAGE_REJECTED={exc}")
        return 2

    print(f"PROVENANCE_PACKAGE=VERIFIED")
    print(f"PROVENANCE_SHA256={hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
