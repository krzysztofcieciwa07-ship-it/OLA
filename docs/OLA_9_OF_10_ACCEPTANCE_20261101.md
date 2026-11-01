# OLA di-OS — 9/10 acceptance contract and rollback gate

Date: 2026-11-01. Status: **DRAFT / NO_GO**. Review SHA is the PR head, never a mutable branch name.
Scope: PR #144 integrates PR #142 and selected security implementations from #119/#132/#133/#134/#135. No deployment or customer charges.

## Evidence received before this commit

- Pre-fix RED on `d00f9ec4132d1d821db350b55fa7f571e71b8272`: two behavioral failures from GitHub Actions: paid webhook incorrectly invoked the agent and `/payment-success` leaked access without a key.
- Fixed integrated SHA `a4f4f58363c0d7810261286c7283647ddf7efe38`: Python Package Gate 41272854102 proves **303 tests, 0 failures, 0 errors, 0 skips**; 15/15 checked PR workflows SUCCESS before main retarget.
- Replit OLA di-OS audit: no active app processes at check time; published deployment `found=false`; GitHub SHA matching unverified; Stripe LIVE delivery unverified.
- Both payment P0 defects now have a negative regression test. No claim of independent human acceptance.

## Binary criteria for an earned score of 9/10

1. **Security + Human Gate (9/10):** 0 open P0/P1 bypasses after independent review; per-tenant authenticated payment status with zero task/report leakage; a signed paid webhook cannot invoke any agent; exact order/session/tenant binding and idempotent replay tested; explicit separate actor, UTC timestamp, reason and evidence SHA for approval; owner- and IGOR-key pinning; migration + rollback rehearsal; at least one independent APPROVED review of the exact source SHA.
2. **Actual agent intelligence (9/10):** real model execution proven by model ID and bounded token usage, not a deterministic stub; independent hidden evaluation of at least 50 representative tasks with expected evidence, >=90% task success, >=95% correct source attribution, zero fabricated fact assertions in security-critical test cases; failure paths return UNKNOWN/REVIEW_REQUIRED; dataset and evaluation version hashed.
3. **Autonomy + improvement (9/10):** at least 20 independent sandbox repair tasks with >=90% safe verified resolution; every mutation has a pre/post test, evidence diff, tested rollback, time/compute budget and human gating for code publication; 0 silent production writes; 0 success claims for skipped tests or unsupported source-to-runtime binding.
4. **Module integration (9/10):** one reproducible Git tree/SHA; passing exact-SHA PR-to-main gates (functional, stress, evidence, provenance, negative mutation, supply chain); verified production Replit process/image/source identity matching signed SHA; NINA→IGOR→Evidence→Human Gate cross-component trace; stable health for a defined observation window; restart persistence and independent replay.
5. **Commercial SaaS (9/10):** one verified LIVE Checkout→verified signed payment→independently authorized execution→tenant-bound Evidence→signed deliverable→customer receipt, with real paid customer consent; secure account login/tenant isolation, billing idempotency, reconciliation/refunds, monitoring, retention policy, support path and documented pricing/terms. Test-mode data never counts as live revenue.

**Scores are not awarded on documentation or green CI names.** Every condition requires concrete logged evidence and an independently checkable artifact. Missing evidence => UNKNOWN, not PASS.

## Safe SQLite rollout checklist (operator action only)

1. Pin signed source SHA, independent approval, health/SLO target, owner actor and rollback authorization.
2. Quiesce paid webhooks and checkout creation before DB changes. Preserve previously confirmed payments and do not auto-run agents.
3. Back up the full SQLite database using its online backup API; preserve WAL handling and SHA-256 of backup, verify backup opens and passes `PRAGMA integrity_check`. Store encrypted backup off-host.
4. Inventory `sqlite_master`: `stripe_checkout_claims`, `stripe_checkout_requests`, `stripe_events`, `evidence_records`. Check the exact column and unique-key schema against the pinned app/models.py, not table-name-only.
5. Test the migration on a restored backup; perform concurrent duplicate-webhook, cross-tenant and interrupted-write tests. Existing ambiguous orders move to reconciliation; never fabricate claim provenance or execution authorization.
6. Take pre-migration checkpoint and keep a rollback to the *prior code+prior database* together. Schema/table removal on live data is prohibited without a signed restoration plan.
7. On controlled deployment, verify exact runtime SHA and targeted health/Evidence/tenant tests with no stored secrets in logs; apply an observation window before a human GO decision.
8. On failure stop paid fulfillment, preserve evidence/confirmed payment data and restore only via independently approved runbook. Do not silently retry uncertain Stripe operations.

## Open blockers

- No independent APPROVED PR review or release signature verification of the integrated SHA.
- No LIVE Stripe E2E, no Replit published deployment or live bound runtime, no confirmed customer receipt.
- Open issues #22, #24, #25. Real OpenAI optional steps in other CI runs may be SKIPPED.
- Documentation contract does not implement a scheduler, prove 9/10 agent quality, or authorize production.

**Release decision: NO_GO / PENDING_HUMAN.**
