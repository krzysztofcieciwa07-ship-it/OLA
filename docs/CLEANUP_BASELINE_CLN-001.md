# CLN-001 Cleanup Baseline

## Scope
Repository hygiene only. No new product functionality or modules.

## Canonical baseline
- Repository: `krzysztofcieciwa07-ship-it/OLA`
- Canonical branch: `main`
- Baseline SHA: `92f2b0d2696583e6a7a75ce44c5fc5296d24e695`
- Cleanup branch: `cleanup/cln-001-safe-20261126`

## Hard safety rules
1. Do not delete a branch until its HEAD SHA and related PR are recorded.
2. Check unique commits, files, tests, migrations, security/evidence changes, workflows, deployment material and documentation before deletion.
3. Salvage required unique value before deleting its source branch.
4. Treat security, evidence, provenance and migration branches as protected until reconciled with current `main`.
5. Work in small cleanup batches.
6. A new regression is NO-GO and requires rollback.
7. Never force-push `main` as part of cleanup.
8. Documentation follows executable code and observed tests.

## Initial inventory findings
- The `main` baseline above is frozen for CLN-001.
- `cleanup/cln-001-safe` and `cleanup/cln-001-safe-20261126` originally pointed at the same baseline SHA; the dated branch is canonical for this batch.
- Several `fix/agent-runtime-minimal-*` branches share the same recorded HEAD SHA `c87cb3c8a798fece4ee18f73ecc648e397b23c24`; they are candidates for deduplication only after PR/unique-value reconciliation.
- Existing open PRs include security/evidence work and must not be bulk-closed without reconciliation.

## Branch disposition states
- `KEEP`
- `SALVAGE`
- `SECURITY-HOLD`
- `SUPERSEDED`
- `DELETE-CANDIDATE`
- `DELETE-VERIFIED`

## Delete gate
Before a branch reaches `DELETE-VERIFIED`, confirm:
- [ ] HEAD SHA recorded
- [ ] Related PR checked
- [ ] Unique commits checked
- [ ] Unique files checked
- [ ] Tests checked
- [ ] Security/evidence/provenance checked
- [ ] Database migrations checked
- [ ] Workflow/CI changes checked
- [ ] Deployment/operations material checked
- [ ] Documentation checked
- [ ] Required unique value salvaged or proven absent

## Post-cleanup gate
After each cleanup batch, compare against this baseline and run the repository's existing tests/build/security/evidence gates. Any new failure stops cleanup and triggers rollback.
