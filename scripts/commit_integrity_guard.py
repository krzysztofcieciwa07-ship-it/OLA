#!/usr/bin/env python3
"""Fail-closed local commit integrity guard for an OLA pull request.

Requires an explicit trusted fingerprint allowlist. No private keys are read.
Run before push: python scripts/commit_integrity_guard.py origin/main HEAD
"""
from __future__ import annotations
import os
import re
import subprocess
import sys

FPR = re.compile(r"(?:[0-9A-F]{40}|[0-9A-F]{64})\Z")


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def verify(base: str, head: str, allowed: set[str]) -> int:
    if not allowed or any(not FPR.fullmatch(x) for x in allowed):
        raise ValueError("trusted signer fingerprint allowlist missing or invalid")
    if not git("rev-parse", "--verify", base + "^{commit}"):
        raise ValueError("base missing")
    if not git("rev-parse", "--verify", head + "^{commit}"):
        raise ValueError("head missing")
    commits = git("rev-list", "--reverse", f"{base}..{head}").splitlines()
    if not commits:
        raise ValueError("no new commits")
    for commit in commits:
        # git verify-commit checks cryptographic validity and key status.
        subprocess.run(["git", "verify-commit", commit], check=True, capture_output=True)
        status = git("log", "-1", "--format=%G?;%GF", commit)
        state, _, fingerprint = status.partition(";")
        if state != "G" or fingerprint.upper() not in allowed:
            raise ValueError(f"untrusted or invalid signature for {commit}")
        print(f"VERIFIED {commit} signer={fingerprint.upper()}")
    print(f"PASS verified_commits={len(commits)}")
    return 0


def main() -> int:
    try:
        raw = os.environ.get("OLA_ALLOWED_SIGNER_FPRS", "")
        allowed = {x.upper() for x in re.split(r"[,;\s]+", raw.strip()) if x}
        base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
        head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
        return verify(base, head, allowed)
    except (ValueError, subprocess.CalledProcessError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
