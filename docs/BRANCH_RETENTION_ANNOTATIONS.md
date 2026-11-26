# Branch Retention Annotations

This file records cleanup disposition for branches that are not being deleted yet. It does not create new product functionality.

## Status legend
- `KEEP` — active/canonical branch that must remain.
- `WORKING` — branch used by the current controlled cleanup.
- `SECURITY-HOLD` — security/evidence/provenance work; removal blocked until reconciled with current `main`.
- `SALVAGE-FIRST` — branch may contain unique useful material; salvage and regression validation required before deletion.
- `HOLD-DEPENDENCY` — branch has a direct PR or integration dependency and cannot be deleted yet.
- `DELETE-VERIFIED` — analysis says the branch reference is redundant and safe to remove when branch deletion is available.
- `REVIEW` — insufficient evidence for deletion; retain until analyzed.

## Canonical / cleanup branches

### `main`
Status: `KEEP`
Reason: canonical source of truth for CLN-001.
Baseline recorded for this batch: `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`.

### `cleanup/cln-001-safe-20261126`
Status: `WORKING`
Reason: controlled cleanup branch containing baseline and risk documentation. Do not delete until CLN-001 is closed and evidence is preserved.

### `cleanup/cln-001-safe`
Status: `REVIEW`
Reason: initially duplicated the CLN-001 baseline. Retain until its lack of unique commits/references is explicitly confirmed, then move to `DELETE-VERIFIED`.

## Agent-runtime duplicate group

The following branches all resolve to commit `c87cb3c8a798fece4ee18f73ecc648e397b23c24`:

- `fix/agent-runtime-minimal-2`
- `fix/agent-runtime-minimal-3`
- `fix/agent-runtime-minimal-4`
- `fix/agent-runtime-minimal-5`
- `fix/agent-runtime-minimal-7`
- `fix/agent-runtime-minimal-8`
- `fix/agent-runtime-minimal-9`
- `fix/agent-runtime-minimal-10`
- `fix/agent-runtime-minimal-11`

Status: `DELETE-VERIFIED`
Reason: same branch tip; no direct PR dependency found for the nine names; the commit added only `tests/test_agent_runtime.py`; current `main` contains that path in a materially expanded form. Detail is recorded in `docs/BRANCH_RISK_AGENT_RUNTIME_DUPLICATES.md`.

These branches are retained temporarily only because deletion of branch references is not being performed by the current cleanup tool path.

## Direct open-PR dependencies: retain

The branches below are directly referenced as heads by open pull requests and are therefore retained until the corresponding PR is reconciled:

- `security/ola100-stripe-live-mode-guard-20261013` — `HOLD-DEPENDENCY`, PR #101.
- `integration/ola96-99-90-owner-sign-20261012` — `HOLD-DEPENDENCY`, PR #100.
- `integration/ai-studio-360-existing-runtime-20261012` — `SALVAGE-FIRST`, PR #99.
- `security/human-gate-atomic-approval-20261012` — `SECURITY-HOLD`, PR #98.
- `security/stripe-session-binding-20261012` — `SECURITY-HOLD`, PR #97.
- `security/combined-gated-candidate-20261012` — `SECURITY-HOLD`, PR #96.
- `security/api-key-v2-cutover-20261012` — `SECURITY-HOLD`, PR #95.
- `security/human-approval-integrity-20261012` — `SECURITY-HOLD`, PR #94.
- `security/evidence-write-boundary-20261012` — `SECURITY-HOLD`, PR #93.
- `fix/igor-failclosed-provenance-20261012` — `SECURITY-HOLD`, PR #92.
- `fix/tenant-hashchain-isolation-20261012` — `SECURITY-HOLD`, PR #91.
- `integration/events-webhooks-20261012` — `SALVAGE-FIRST`, PR #90.
- `security/restore-signature-production-gates-20261011` — `SECURITY-HOLD`, PR #89.
- `feat/verified-console-20261011` — `SALVAGE-FIRST`, PR #88.
- `feat/public-threat-intelligence-20261011` — `SALVAGE-FIRST`, PR #86.
- `hardening/replay-record-validation-20261011` — `SECURITY-HOLD`, PR #85.
- `hardening/human-gate-contract-20261011` — `SECURITY-HOLD`, PR #84.
- `integrate/vantage-gate-20261011` — `HOLD-DEPENDENCY`, PR #83.
- `alert-autofix-1` — `SECURITY-HOLD`, PR #82.
- `security/igor-provenance-consistency-20261011` — `SECURITY-HOLD`, PR #80.
- `security/evidence-hash-v2-20261011` — `SECURITY-HOLD`, PR #79.
- `integration/all-ola-20261010` — `HOLD-DEPENDENCY`, PR #76.
- `security/stripe-session-isolation-20261010` — `SECURITY-HOLD`, PR #75.
- `security/approval-bypass-failclosed-20261010` — `SECURITY-HOLD`, PR #74.
- `security/codeql-sarif-failclosed-20261010` — `SECURITY-HOLD`, PR #73.
- `fix/watchdog-failclosed-autoflow-20261010` — `SECURITY-HOLD`, PR #71.
- `fix/production-gate-evidence-20261010` — `SECURITY-HOLD`, PR #64.
- `feat/traceforge-v0` — `SALVAGE-FIRST`, PR #61.
- `forensic/semantic-closure-2026-10-02` — `SECURITY-HOLD`, PR #60.
- `cfr18-forensic` — `SECURITY-HOLD`, PR #40.
- `feat/decision-fabric-jev` — `SALVAGE-FIRST`, PR #37.

## Same-tip duplicate candidates awaiting dependency reconciliation

These are retained until their PR/history dependencies and unique-value status are checked:

- `fix/crypto-monitor-canonical-reconciliation`
- `fix/crypto-monitor-e2e-hardening`
- `feat/noncustodial-crypto-payment-monitor`
  - Same recorded tip: `42ba5be3924d7901099e899790e13afbcfbca155`.
  - Status: `REVIEW`.

- `fix/final-production-gate-20261006`
- `fix/final-production-gate-stage-20261006`
  - Same recorded tip: `9990e9f990cee87bc0d00c5c99566d4e436238f0`.
  - Status: `REVIEW`.

- `feat/ola-staging-bff-bootstrap-clean-20261108`
- `integration/jev-decision-fabric-20261106`
  - Same recorded tip: `6dff9c43ccd5a6892a50d1f59363d232b07ceafb`.
  - Status: `REVIEW`.

- `feat/runtime-image-attestation-20261107`
- `integration/ola-first-five-closure-20261106`
- `integration/replit-bff-recovery-20261107`
  - Same recorded tip: `8e56b33df9a3e2806f3709fca90b07e4e595d28f`.
  - Status: `REVIEW`.

## Default rule for every other branch

Status: `REVIEW` until inspected.

No branch outside an explicitly documented `DELETE-VERIFIED` set may be deleted. For every remaining branch, cleanup must record HEAD SHA, PR/reference dependency, reachability from current `main`, unique files/tests, security/evidence/provenance content, migrations, CI/workflow dependencies, operations/deployment material and documentation before deciding `KEEP`, `SALVAGE-FIRST`, `SECURITY-HOLD` or `DELETE-VERIFIED`.
