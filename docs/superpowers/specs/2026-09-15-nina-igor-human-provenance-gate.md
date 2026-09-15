# NINA → IGOR → HUMAN Provenance Gate Specification

**Status:** APPROVED FOR IMPLEMENTATION
**Baseline:** `8b8ea418c9f0f45b0696749e72ed5bc00c1aaf0c`

## Goal
Build a product-layer provenance gate in which NINA executes and produces a candidate result, IGOR independently recomputes and verifies provenance, and HUMAN makes an explicit decision whenever policy requires authorization.

## Canonical chain

`TASK → CLAIM → SOURCE → RAW_ARTIFACT → HASH → EXTRACTION → EVIDENCE → CORRELATION → IGOR_VERIFICATION → PROVENANCE_GATE → HUMAN_DECISION`

## Required invariants

1. Every candidate result is bound to one task ID.
2. Every claim must have a source.
3. Every source must identify a captured raw artifact.
4. Raw artifacts are immutable and SHA-256 bound.
5. Evidence must point back to an artifact and extraction location/method.
6. Claims and evidence must have explicit correlation IDs.
7. NINA may not certify its own result.
8. IGOR must independently recompute provenance, integrity, correlations and contradictions.
9. IGOR can emit `VERIFIED`, `REVIEW`, `BLOCK`, or `UNKNOWN`.
10. Missing mandatory provenance is not converted into low confidence; it is `UNKNOWN` or `BLOCK` according to the rule.
11. `UNKNOWN → VERIFIED` is forbidden.
12. An unresolved contradiction produces `REVIEW`.
13. Human authorization is a separate record from AI verification.
14. Decisions must remain traceable to the evidence chain.
15. The complete execution must be replayable from the immutable ledger.
16. The audit trail is append-only and hash chained.
17. Invalid verifier state, missing verifier output, or integrity failure fails closed.

## Independence boundary

NINA writes candidate/provenance material but its status is not trusted by IGOR. IGOR reads the stored records and independently recomputes the checks without importing NINA verification logic. The standalone verifier is the authority used by CI for the final gate assertion.

## Gate semantics

- `VERIFIED`: all mandatory provenance and verification invariants pass; no unresolved contradiction exists.
- `REVIEW`: evidence is present but a contradiction or policy condition requires human review.
- `BLOCK`: mandatory provenance/integrity is absent or invalid, or an explicit blocking rule fires.
- `UNKNOWN`: the verifier cannot establish the required fact from available evidence.

## Human boundary

Where policy marks human authorization as required, IGOR verification does not authorize the action. The system records a separate HUMAN decision of `APPROVE` or `REJECT`. No automatic action may be treated as human-authorized.

## Replay

A replay must reconstruct task, actions, source captures, artifacts, hashes, evidence, correlations, IGOR verification and human decision from the immutable records and reproduce the gate outcome.

## E2E success contract

The implementation is not PASS because an endpoint returns HTTP 200 or a status string says `VERIFIED`. E2E PASS requires runtime evidence proving the complete chain plus an independent verifier that recomputes the result.

## Non-goals

This phase does not claim production external-LLM inference. The existing deterministic runtime is used only as a controlled execution substrate until an external model integration is separately proven.
