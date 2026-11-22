# OLA execution checkpoint — 2026-11-22

## Canonical source
- Repository: `krzysztofcieciwa07-ship-it/OLA`
- Main: `b3c649f8412fee9b0554863a9bba60fbe7d01550`
- PR #276 OIDC verifier: merged.
- This checkpoint is evidence navigation and dependency tracking, not a production release attestation.

## Exact-head candidate status

| PR | Exact head | Check-runs | Decision |
|---|---|---|---|
| #280 signed Human Gate contract | `0cee5de4d196451f6cc87d02629aae6260b08dec` | 35 SUCCESS, 2 SKIPPED, 1 CANCELLED, 0 FAILED | Draft; current-head independent review missing. APPROVED reviews are bound to earlier commits. |
| #282 tenant membership resolver (stacked on #280) | `7733cc2e231fe0f11f367bd8194d2408ff3b3f64` | 20 SUCCESS, 1 SKIPPED, 0 FAILED | Draft; OIDC membership is still not wired into approval routes or workers. |
| #273 capability voucher prototype | `6d8011717dd63c7df8442b5009f718ada6582aee` | 35 SUCCESS, 2 SKIPPED, 0 FAILED | Draft; local SQLite replay ledger, not shared multi-host production storage. |
| #283 PostgreSQL durable replay (stacked on #273) | `688fc9055f809eb26ea79c032beac295dc3275ad` | 19 SUCCESS, 1 SKIPPED, 0 FAILED, 0 IN_PROGRESS; PostgreSQL contract 9 passed | Draft; no route integration. |
| #274 tenant-scoped Evidence API | `58941d249c843a585a326259a34fd1f46f86cc57` | 35 SUCCESS, 2 SKIPPED, 0 FAILED | Draft; older runtime evidence is not reused as proof for this head. |
| #272 writer-universe audit | `5f383614e01f93ac0db35511608658a796073ebf` | 16 SUCCESS, 1 SKIPPED, 0 FAILED | Draft; source audit only, no production DB/IAM attestation. |
| #281 CI trigger reliability | `3a354a6767d624c3007f609c81b6f636b6863a7b` | 35 SUCCESS, 2 SKIPPED, 0 FAILED | Draft; candidate fix, not merged. |

Skipped checks are not counted as PASS. CI results are bound only to the listed exact heads.

## Main final-gate defect

- PR #277 handoff head: `fde3ddcf1d89929506bdfbc712723c9925f935bb`.
- Final Production Gate run `44953674326` failed closed because the main source lacked the `OLA paid-order PostgreSQL contract` producer.
- PR #281 candidate has the producer and its exact-head Final Production Gate is SUCCESS, but #281 is not merged. Therefore the main defect is **not resolved**.
- Do not merge #277 as a release claim or use its failing gate as production evidence.

## Human review and governance

- #280 has no APPROVED review bound to current head `0cee5de4...`; its latest recorded approval is bound to `1c8bfcfc...`.
- #282, #273, #283, #274, #272 and #281 remain drafts and require independent review.
- Last verified effective main rules snapshot (not rechecked in this checkpoint): main was not protected by required checks; ruleset `25853037` covered deletion/non-fast-forward only. Issue #150 remains the governance/HUMAN_GATE reference. No access or branch-rule mutation was made.

## Dependency checklist

### P0 — identity, approval and enforcement
- [x] #276 OIDC verifier merged.
- [x] #280 signed-approval contract candidate has exact-head CI results.
- [x] #282 OLA-owned tenant membership model/resolver candidate has exact-head CI results.
- [ ] Fresh independent review of #280 current head and merge decision.
- [ ] Review #282; retarget to main only after #280 integration and revalidation.
- [ ] Wire verified OIDC + current membership + role + membership version into the actual approval route.
- [ ] Bind signed contract to the exact resource, evidence tip, policy, requester/reviewer separation and effect.
- [ ] Enforce one-time nonce, expiry, revocation/version change and replay at the effect boundary.
- [ ] Integrate voucher verification into one shared execution choke point; close `/agent-run`, `/nina-run`, worker and other bypasses.
- [ ] #283 durable PostgreSQL replay candidate CI/review/DB-owner acceptance; integrate only after dependencies.

### P0/P1 — data and execution boundary
- [ ] Writer/database integrity and tenant isolation (including effective DB privileges and RLS/context).
- [ ] Sandbox depth limits and network allowlists.
- [ ] Telemetry and run lifecycle audit from `run.start` to `run.end`.
- [ ] Stress, fault-injection, restart and recovery proof on exact runtime source.
- [ ] Reproducibility and supply-chain attestations.
- [ ] Effective branch protection and required checks.
- [ ] Release manifest, E2E and final production gate on exact integrated main SHA.

## Non-authorized actions

No production/staging migration, runtime DB grant, RLS change, secret access, Railway mutation, deployment, payment or external effect was performed. No PR was merged. All candidates remain subject to review and exact integrated-main revalidation.


## CI update — 2026-11-22

- PR #283 exact head `688fc9055f809eb26ea79c032beac295dc3275ad`: 19 SUCCESS, 1 SKIPPED (`igor-independent`), 0 FAILED, 0 IN_PROGRESS. All 17 workflow-run records completed SUCCESS. PostgreSQL contract run `44965673398` returned `9 passed in 1.60s` and asserted exact checkout SHA.
- PR #282 exact head `7733cc2e231fe0f11f367bd8194d2408ff3b3f64`: 20 SUCCESS, 1 SKIPPED, 0 FAILED, 0 IN_PROGRESS; all 18 workflow-run records completed SUCCESS, including the real Ollama runtime gate.
- These results do not replace independent review, route integration or production DB/RLS proof.
