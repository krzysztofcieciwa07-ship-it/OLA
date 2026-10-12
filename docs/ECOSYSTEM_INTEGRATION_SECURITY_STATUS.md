# OLA ecosystem security integration status

This document describes integration controls, not a production certificate.

## Scope
- OLA core: execution gate remains authoritative.
- Vantage: heuristic advisory only, cannot authorize execution.
- Evidence Gateway: requires independent sign/verify/tamper/replay evidence before promotion.
- CFR-18: isolated scenario, not automatically production code.
- ZBook: local signed-commit preparation, not remotely verified.

## Fail-closed conditions
1. A missing trusted signer allowlist blocks signature verification.
2. Unverified/unsigned commits block production promotion.
3. CI green alone is insufficient: provenance, tamper, replay and human approval must be independently confirmed.
4. Synthetic/deterministic LLM output is not evidence of live inference.
5. A repository hook is inactive until installed and tested locally.
6. No direct main push; no production deployment from a draft PR.

## Local setup (operator-controlled)
- Configure Git to sign commits with an authorized GPG key.
- Publish only the public key to GitHub.
- Configure OLA_ALLOWED_SIGNER_FPRS to the approved fingerprint in the repository's Actions variables and the local environment.
- Install the pre-push hook explicitly (copy scripts/pre-push-commit-integrity to .git/hooks/pre-push, ensure executable) and test a rejected unsigned push.
- Review the commit range against the frozen base, then sign/recreate the history without losing tree changes.
- Verify exact source SHA and successful required checks before human approval.

## Known open issues
- PR #83 includes commits created without cryptographic signatures.
- Production signature gate reports missing/invalid fingerprint allowlist.
- Hook installation on the ZBook is not verified.
- Full Vantage-to-OLA runtime wiring and independent end-to-end evidence are not verified.
- No production deployment evidence has been established.

Status: BLOCKED for merge and production.
