# PR #277 exact-source final-gate diagnosis — 2026-11-21

## Scope and source

- PR: https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/277
- Branch: `docs/ola-operational-handoff-20261121`
- Exact source SHA inspected: `e6cc473b360f9a0e155f28861e6dc1c351b92f6d`
- Base SHA: `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`
- Final production gate run: https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44928909825
- Run conclusion: **FAIL / fail-closed**. No merge or deployment was performed.

## Exact check-run inventory

At the inspected SHA, GitHub reported 34 check-runs:

- 31 SUCCESS
- 2 SKIPPED: `igor-independent`, `scorecard`
- 1 FAILURE: `final-production`

The exact-source gate-status artifact reports 23 completed required-gate entries as SUCCESS, with no named failed producer, but two required producers are absent:

1. `Evidence Cryptography V4 Contract`
2. `OLA paid-order PostgreSQL contract`

The missing producers are **UNKNOWN / missing**, not PASS and not evidence that the contracts failed. The final gate's `Verify required evidence gates` step failed; release-image build, source/image snapshots and attestations were skipped after the fail-closed decision.

## Artifact integrity

- Artifact ID: `14718081696`
- Artifact ZIP digest from GitHub metadata and independently recomputed local SHA-256: `0f48a86adc3235769e17d6f7748e2de9dbfa6e2f6f046b2de909f15d5c37b928`
- `production-manifest.json` SHA-256: `390aed5a69600cb1328e1a59c01f378242264109c2aaf015c0763373d62383c4`
- Manifest source SHA: `e6cc473b360f9a0e155f28861e6dc1c351b92f6d`
- Manifest status: `BLOCKED`
- Source attestation: `NOT_PERFORMED`
- Release-image attestation: `NOT_PERFORMED`

The artifact was inspected read-only. It contains the gate-status manifest and run snapshots; no secret or DSN was extracted.

## Consequence / next closure evidence

The missing Evidence V4 and PostgreSQL contract producers are the concrete reason the final production gate cannot complete for this exact source. PR #275 is the existing candidate that removes path-filter omissions; it remains unmerged, so its change is not effective on the inspected source.

Do not bypass, relabel, or infer PASS from other successful checks. Required closure evidence is:

- the two producer workflows complete SUCCESS for the exact source SHA;
- the final production gate is rerun and completes SUCCESS on that same SHA;
- skipped gates remain explicitly unresolved;
- independent review and all P0 invariants remain separate acceptance requirements.

**Decision:** merge train remains STOP. This is pre-merge CI evidence only, not production GO, deployment, source/image attestation, or Human Gate approval.
