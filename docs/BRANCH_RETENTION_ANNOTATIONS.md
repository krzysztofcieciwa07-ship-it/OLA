# Branch Retention Annotations

This registry controls branch cleanup. It does not introduce product functionality.

## Status legend
- `KEEP` — canonical branch that must remain.
- `WORKING` — current controlled cleanup branch.
- `SECURITY-HOLD` — security/evidence/provenance material; no deletion before reconciliation.
- `SALVAGE-FIRST` — unique useful material may exist; selective salvage and validation required before deletion.
- `HOLD-DEPENDENCY` — direct PR/integration dependency exists.
- `DELETE-VERIFIED` — branch reference was analyzed and may be removed without changing `main` history.
- `REVIEW` — insufficient evidence; retain.

## Canonical
- `main` — `KEEP`. CLN-001 baseline: `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`.
- `cleanup/cln-001-safe-20261126` — `WORKING`.
- `cleanup/cln-001-safe` — `REVIEW` until unique-reference verification is closed.

## DELETE-VERIFIED

### Agent-runtime duplicate group
Shared tip: `c87cb3c8a798fece4ee18f73ecc648e397b23c24`.
- `fix/agent-runtime-minimal-2`
- `fix/agent-runtime-minimal-3`
- `fix/agent-runtime-minimal-4`
- `fix/agent-runtime-minimal-5`
- `fix/agent-runtime-minimal-7`
- `fix/agent-runtime-minimal-8`
- `fix/agent-runtime-minimal-9`
- `fix/agent-runtime-minimal-10`
- `fix/agent-runtime-minimal-11`
Report: `docs/BRANCH_RISK_AGENT_RUNTIME_DUPLICATES.md`.

### Final-production-gate duplicate pair
Shared tip: `9990e9f990cee87bc0d00c5c99566d4e436238f0`.
- `fix/final-production-gate-20261006`
- `fix/final-production-gate-stage-20261006`
Reason: shared workflow change is reachable from default-branch history and represented by the broader current production-gate workflow.
Report: `docs/BRANCH_RISK_FINAL_PRODUCTION_GATE_DUPLICATES.md`.

### Staging/integration duplicate pair
Shared tip: `6dff9c43ccd5a6892a50d1f59363d232b07ceafb`.
- `feat/ola-staging-bff-bootstrap-clean-20261108`
- `integration/jev-decision-fabric-20261106`
Reason: shared tip changes only `README.md`; commit is in default-branch history; current `main` has a later expanded README; no direct PR head dependency was found for either branch.
Report: `docs/BRANCH_RISK_STAGING_INTEGRATION_DUPLICATES.md`.

## SALVAGE-FIRST
- `fix/crypto-monitor-canonical-reconciliation`
- `fix/crypto-monitor-e2e-hardening`
- `feat/noncustodial-crypto-payment-monitor` — historical closed draft PR #265.
- `integration/ai-studio-360-existing-runtime-20261012` — PR #99.
- `integration/events-webhooks-20261012` — PR #90.
- `feat/verified-console-20261011` — PR #88.
- `feat/public-threat-intelligence-20261011` — PR #86.
- `feat/traceforge-v0` — PR #61.
- `feat/decision-fabric-jev` — PR #37.
See `docs/SALVAGE_FIRST_STATUS.md`.

## SECURITY-HOLD / HOLD-DEPENDENCY
- `security/ola100-stripe-live-mode-guard-20261013` — `HOLD-DEPENDENCY`, PR #101.
- `integration/ola96-99-90-owner-sign-20261012` — `HOLD-DEPENDENCY`, PR #100.
- `security/human-gate-atomic-approval-20261012` — `SECURITY-HOLD`, PR #98.
- `security/stripe-session-binding-20261012` — `SECURITY-HOLD`, PR #97.
- `security/combined-gated-candidate-20261012` — `SECURITY-HOLD`, PR #96.
- `security/api-key-v2-cutover-20261012` — `SECURITY-HOLD`, PR #95.
- `security/human-approval-integrity-20261012` — `SECURITY-HOLD`, PR #94.
- `security/evidence-write-boundary-20261012` — `SECURITY-HOLD`, PR #93.
- `fix/igor-failclosed-provenance-20261012` — `SECURITY-HOLD`, PR #92.
- `fix/tenant-hashchain-isolation-20261012` — `SECURITY-HOLD`, PR #91.
- `security/restore-signature-production-gates-20261011` — `SECURITY-HOLD`, PR #89.
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
- `forensic/semantic-closure-2026-10-02` — `SECURITY-HOLD`, PR #60.
- `cfr18-forensic` — `SECURITY-HOLD`, PR #40.

## NEXT: runtime-attestation/integration group
Shared recorded tip: `8e56b33df9a3e2806f3709fca90b07e4e595d28f`.
- `feat/runtime-image-attestation-20261107`
- `integration/ola-first-five-closure-20261106`
- `integration/replit-bff-recovery-20261107`
Status: `REVIEW` pending reachability, PR/history dependencies, unique files/tests, release/evidence dependencies, migrations, CI and operations material.

## Completeness rule
Every other branch remains `REVIEW` until individually or as a proven identical-tip group analyzed. No branch outside `DELETE-VERIFIED` may be deleted.
