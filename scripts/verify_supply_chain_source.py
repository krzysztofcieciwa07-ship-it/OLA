#!/usr/bin/env python3
"""Bind the checked-out source to an image alongside GitHub's event provenance.

Verification input must be the output of successful `gh attestation verify`
calls, with repository, workflow, certificate source SHA and predicate pinned.
This module checks their signed payloads; it does not verify signatures itself.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PREDICATE = "https://github.com/krzysztofcieciwa07-ship-it/OLA/attestations/source-binding/v1"
SLSA = "https://slsa.dev/provenance/v1"
STATEMENT = "https://in-toto.io/Statement/v1"


def expected_binding(env):
    source, event = env["SOURCE_SHA"], env["GITHUB_SHA"]
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (source, event)):
        raise ValueError("invalid source/event commit")
    return {
        "source": {"repository": env["GITHUB_REPOSITORY"], "commit": source},
        "workflow": {"event_commit": event, "run_id": env["GITHUB_RUN_ID"],
                     "run_attempt": env["GITHUB_RUN_ATTEMPT"]},
    }


def record_checkout(env):
    predicate = expected_binding(env)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != predicate["source"]["commit"]:
        raise ValueError("checkout does not match SOURCE_SHA")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("tracked checkout is modified before build")
    return predicate


def statements(results, predicate_type, digest):
    if not isinstance(results, list) or not results:
        raise ValueError("no verified attestations")
    found = []
    for item in results:
        statement = item["verificationResult"]["statement"]
        if statement.get("_type") != STATEMENT or statement.get("predicateType") != predicate_type:
            raise ValueError("unexpected attestation type")
        if not any(s.get("digest", {}).get("sha256") == digest for s in statement.get("subject", [])):
            raise ValueError("attestation subject does not match image")
        found.append(statement["predicate"])
    return found


def verify_source(provenance, bindings, digest, env):
    expected = expected_binding(env)
    source_claims = statements(bindings, PREDICATE, digest)
    if not any(claim == expected for claim in source_claims):
        raise ValueError("signed checkout source or execution context mismatch")
    # GitHub's SLSA predicate identifies the event commit (PR merge SHA), not
    # an explicit head-SHA checkout. Keep the two claims separate and require both.
    slsa = statements(provenance, SLSA, digest)
    if not any(dep.get("digest", {}).get("gitCommit") == env["GITHUB_SHA"]
               for claim in slsa
               for dep in claim.get("buildDefinition", {}).get("resolvedDependencies", [])):
        raise ValueError("SLSA workflow event commit mismatch")
    return {"source_sha": env["SOURCE_SHA"], "workflow_event_sha": env["GITHUB_SHA"],
            "source_binding": "VERIFIED", "slsa_workflow_provenance": "VERIFIED"}


def main():
    if sys.argv[1:] == ["record"]:
        Path("source-binding.json").write_text(json.dumps(record_checkout(os.environ), sort_keys=True) + "\n")
    elif sys.argv[1:] == ["verify"]:
        with open("ola-image.tar", "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result = verify_source(json.loads(Path("attestation-verification.json").read_text()),
                               json.loads(Path("source-binding-verification.json").read_text()),
                               digest, os.environ)
        print(json.dumps(result, sort_keys=True))
    else:
        raise ValueError("expected record or verify")


if __name__ == "__main__":
    main()
