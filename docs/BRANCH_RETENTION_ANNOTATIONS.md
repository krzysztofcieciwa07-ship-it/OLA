# Branch Retention Annotations

This registry controls branch cleanup. It does not introduce product functionality.

## Canonical
- `main` — `KEEP`; CLN-001 baseline `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`.
- `cleanup/cln-001-safe-20261126` — `WORKING`.

## DELETE-VERIFIED

### Obsolete cleanup branch
- `cleanup/cln-001-safe`
Tip: `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`, exactly the recorded CLN-001 baseline.
PR dependency: none found.
Unique cleanup commits/files: none; its tip is the baseline itself, while the dated working branch contains the actual CLN-001 documentation commits.
Disposition: `DELETE-VERIFIED`. Delete the branch reference only; preserve `main` and `cleanup/cln-001-safe-20261126`.

### Agent-runtime duplicates — `c87cb3c8a798fece4ee18f73ecc648e397b23c24`
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

### Final-production-gate duplicates — `9990e9f990cee87bc0d00c5c99566d4e436238f0`
- `fix/final-production-gate-20261006`
- `fix/final-production-gate-stage-20261006`
Report: `docs/BRANCH_RISK_FINAL_PRODUCTION_GATE_DUPLICATES.md`.

### Staging/integration duplicates — `6dff9c43ccd5a6892a50d1f59363d232b07ceafb`
- `feat/ola-staging-bff-bootstrap-clean-20261108`
- `integration/jev-decision-fabric-20261106`
Report: `docs/BRANCH_RISK_STAGING_INTEGRATION_DUPLICATES.md`.

### Runtime-attestation/integration duplicates — `8e56b33df9a3e2806f3709fca90b07e4e595d28f`
- `feat/runtime-image-attestation-20261107`
- `integration/ola-first-five-closure-20261106`
- `integration/replit-bff-recovery-20261107`
Report: `docs/BRANCH_RISK_RUNTIME_ATTESTATION_DUPLICATES.md`.

## SALVAGE-FIRST
- `fix/crypto-monitor-canonical-reconciliation`
- `fix/crypto-monitor-e2e-hardening`
- `feat/noncustodial-crypto-payment-monitor` — closed draft PR #265.
- `integration/ai-studio-360-existing-runtime-20261012` — PR #99.
- `integration/events-webhooks-20261012` — PR #90.
- `feat/verified-console-20261011` — PR #88.
- `feat/public-threat-intelligence-20261011` — PR #86.
- `feat/traceforge-v0` — PR #61.
- `feat/decision-fabric-jev` — PR #37.
See `docs/SALVAGE_FIRST_STATUS.md`.

## SECURITY-HOLD / HOLD-DEPENDENCY
Existing security/evidence/provenance heads remain retained until individual reconciliation. See `docs/CLN-001_EXECUTION_MAP.md`; no such branch is delete-approved by this update.

## Next work in plan
1. Continue branch duplicate discovery beyond analyzed identical-tip groups.
2. Execute SALVAGE-FIRST narrow comparisons, starting with the Human Gate change inside PR #99 separately from Studio/UI material.
3. Continue security/evidence reconciliation.
4. Only then proceed to workflow/file cleanup and full regression.

## Completeness rule
Every other branch remains `REVIEW` until individually or as a proven identical-tip group analyzed. No branch outside `DELETE-VERIFIED` may be deleted.
