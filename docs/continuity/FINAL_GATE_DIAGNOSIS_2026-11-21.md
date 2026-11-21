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

---

## Exact-source revalidation — 2026-11-21 19:05 UTC

- PR #277 current source at this observation: `592a2d1b8d327e06c86fe71970395abeb9b6c0a1`.
- Final Production Gate run: [#44934515322](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44934515322), exact PR SHA, **FAIL / fail-closed**.
- Job `final-production`: job ID `136938109742`; `Verify required evidence gates` failed. Build, export and attestations skipped.
- Gate-status `missing`: `Evidence Cryptography V4 Contract` and `OLA paid-order PostgreSQL contract`. `failed={}`, `pending={}`; this is producer absence, not test failure.
- Artifact ID `14720107351`; GitHub digest and locally recomputed ZIP SHA-256: `726a6c88f1834b8499cea4bcb0d7636392aa47efa8cb954abc8a40c62f85e13`.
- Gate-status JSON SHA-256: `92b56edfe13e74cf4948ace423c77578496a7063e3b55fc098f673a405d34983`.
- Production manifest SHA-256: `3d4e030f9d0921f7ee2895cb64185c4f4fe27b7a5ce0124c7507e3ba879a367d`; status `BLOCKED`; source and image attestations `NOT_PERFORMED`.
- Other required checks on this exact SHA include successful Python package CI, supply-chain evidence gate, CodeQL, Ollama runtime, Evidence Graph, staging rehearsal, stress, and provenance mutation; they do not substitute for the two absent producers.
- The supply-chain gate on this exact PR head is SUCCESS. This does not resolve the 23 Gitleaks findings on main.

## Existing trigger-fix candidates — exact-head evidence

The two missing producer workflows are the same trigger-coverage defect addressed by existing candidates; neither is merged into main:

- PR #275, head `4cd0aea0364b7e22a3d924af850759c26b0b4c9a`: Final Production Gate run [#44868191910](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44868191910) SUCCESS. Artifact #14693056313, SHA-256 `fd4a8ca2ed9e6047d239e4633cc1dce589981da782c3bfe4f65aa4b8c19e064f`. Candidate removes path filters from required producers and includes the main-run cancellation protection. PR remains OPEN/DRAFT with no submitted independent review at the latest review read.
- PR #268, head `85ebc04fb7337888c810b158b10128735a752162`: Final Production Gate run [#44877648940](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44877648940) SUCCESS. Artifact #14697021225, SHA-256 `a18f71840dcffd04e58b2989ccd95035083ed09aee6f3e8d8003d21fd56232e1`. It contains the broader panel/workflow candidate with the same producer-trigger fix; it also remains OPEN/DRAFT and has no submitted independent review.

Do not merge both branch trees blindly: #268 and #275 overlap in the trigger/test files; #275 carries a separate cancellation-protection change. No merge, deployment or external mutation was performed in this revalidation.

**Current decision remains MERGE TRAIN STOP.** Exact-source CI evidence for these candidate trigger fixes is positive, but missing producers on PR #277 remain UNKNOWN until the fix is integrated and rerun on the resulting exact SHA; main governance, tenant/RLS, database target mapping and production Human Gate remain separate blockers.


## Exact-source revalidation — 2026-11-21 20:28 UTC

- PR #277 head: `6b1aa56c88c6a141de9ff8207b871a18a9c5fc3d`; base/main SHA: `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`.
- GitHub check-runs on this exact head: 34 total — 31 SUCCESS, 2 SKIPPED (`igor-independent`, `scorecard`), 1 FAILURE (`final-production`). The exact-head Supply Chain Evidence Gate/Gitleaks check is SUCCESS; this does not close the 23 findings on main.
- Final Production Gate: [run #44939238948](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/44939238948), job `final-production` ID `136952566613`. Step `Verify required evidence gates` failed closed. `failed={}`, `pending={}`; the two absent producers remain `UNKNOWN`: `Evidence Cryptography V4 Contract` and `OLA paid-order PostgreSQL contract`. Release-image build/export and attestations were skipped.
- Artifact #14722131738: GitHub digest / ZIP SHA-256 `3febc08a36ec323994bb9236abdde09c70fcb168eb5110365736e02d7cace119`. `production-manifest.json` SHA-256 `60cdb44f05ef0cb580ced0becce6eec65f6faa730d85bdc93811ecdf68758399`; manifest status `BLOCKED`; source/image attestations `NOT_PERFORMED`.
- Main branch remains SHA `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`. GitHub branch metadata reports `protection.enabled=false`, required-check enforcement `off`, and no contexts/checks. The dedicated branch-protection API endpoint returned 403 to the connected integration; no governance changes were made.
- PR #277 remains OPEN/DRAFT; GitHub currently reports mergeable=true but mergeable-state `unstable`; no independent review was submitted. No merge or deployment was performed.

## Staging deployment failure — read-only log inspection

- Railway project: `OLA FastAPI Staging`; environment: `Ola di-os`; API deployment `ac7efe87-b02d-4b23-a422-a459498cc054`, created 2026-11-21 17:05 UTC, status `FAILED`.
- Source commit recorded by build: `393cc56dcd8c1a749cf11d4306d1e247144139cb`; branch `feat/ola-staging-bootstrap-20261108`.
- Failure occurred in `scripts/migrate_postgres.py` while opening the PostgreSQL connection: password authentication rejected for role `ola_migrator`. DB host/IP details are intentionally omitted. No successful connection or migration is evidenced by these logs; do not infer a DB write or target mapping.
- API service has no persistent volume in this environment. Neon `OLA_DATABASE_URL` mapping to a specific project/branch remains UNKNOWN. Production project `Ola di-os` remains separate from this staging project.
- Next owner action: authorized operator must validate the intended Neon target and role/credential mapping without exposing DSN/secret values; provide sanitized identity/target evidence. Do not rotate/change credentials or retry migration from automation.

**Decision:** MERGE TRAIN STOP. These are fresh source-bound CI and staging-failure observations only; neither establishes production readiness or P0 closure.
