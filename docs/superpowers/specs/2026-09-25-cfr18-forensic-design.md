# CFR-18 Forensic Scenario Design

## Goal
Recreate CFR-18 as a real, runnable incident scenario inside the existing OLA repository, using the repository's evidence/hash-chain concepts while keeping the scenario self-contained and independently verifiable.

## Scope
CFR-18 is implemented under `scenarios/cfr-18/` as a Docker Compose incident lab. It must provide a reproducible Queue Resurrection fault, per-seed mutation, evidence capture, tamper-evident scoring, adaptive hidden stability, and a forensic proof bundle.

## Existing substrate verified
The OLA repository exists on GitHub and its `main` branch contains application/runtime, hash-chain, Human Gate, Nina/Igor, provenance and evidence-related workflows. No existing CFR-18 implementation or Vantage-named scenario directory was found by repository code search. Therefore CFR-18 is added as a self-contained scenario rather than pretending an existing CFR-18/Vantage implementation already exists.

## Architecture
1. `scenarios/cfr-18/services/` contains the intentionally vulnerable API/worker/SQLite application.
2. `scenarios/cfr-18/ci/` contains mutation, evidence vault, assertions, hidden checks, scoring, incident generation and forensic bundling.
3. `scenarios/cfr-18/scripts/` contains traffic, kill and probe helpers.
4. `scenarios/cfr-18/evidence/` is runtime output and is excluded from source control.
5. `scenarios/cfr-18/docker-compose.yml` provides the complete live stack.

## Forensic invariants
- Evidence is append-only at the chain layer and every chain entry contains `prev_hash` and a content hash.
- Score computation must fail closed when the chain is invalid or missing.
- A score is not forensic certification; certification requires runtime execution plus independent verification.
- The final bundle records source commit, scenario seed, container state, evidence hashes, chain verification, assertions, score, tamper test and replay result.
- SHA-256 provides tamper evidence; Ed25519 signing is a separate v2 capability and must not be claimed in v1.
- Hidden checks must not disclose the exact stability threshold.

## Success criteria
A successful run must demonstrate: stack starts; fault is observable; fault is triggered; fix is applied; health remains stable for the required window; assertions pass; score is computed only from intact evidence; an intentional evidence mutation is detected; a clean replay can reproduce the expected scenario state; and the final bundle contains hashes linking the artifacts to the exact source commit and session.

## Non-goals
No production payment activation, no customer data, no claim of immutable external storage, no Ed25519 signature, and no claim of independent Igor verification until those mechanisms are actually executed and evidenced.
