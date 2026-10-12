# GitHub PR #83: independent merge checklist

This checklist is deliberately fail closed. It does not attest completion.

- [ ] Freeze expected base and head SHAs.
- [ ] Ensure all PR commits are signed by a trusted authorized key and independently verified.
- [ ] Confirm Actions variable OLA_ALLOWED_SIGNER_FPRS is configured to that key.
- [ ] Run all tests and inspect failures, skipped tests, and workflow permissions.
- [ ] Confirm Vantage advisory signals cannot bypass ExecutionSafetyGate.
- [ ] Test Unicode, encoded payloads, false positives, and unknown sources.
- [ ] Confirm real Ollama runtime evidence (not deterministic fallback).
- [ ] Independently verify source binding, signatures, tamper rejection, replay and evidence hashes.
- [ ] Obtain explicit human approval.
- [ ] Merge only after checks pass; attest and verify release image after main SHA is frozen.
- [ ] Deploy to target environment and record runtime health, provenance and rollback result.

No unchecked item may be represented as VERIFIED.
