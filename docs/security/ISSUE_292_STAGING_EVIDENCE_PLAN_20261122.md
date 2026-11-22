# Issue #292 — signed Human Gate staging evidence plan (NO MUTATION)

## Stable task manifest
- Stable ID: OLA-HG-292
- Issue: #292
- Priority: P0
- Owner: coordinator; NINA implementation lane; IGOR independent evidence verification; human owner/admin for identity, DB and signer controls
- Dependencies: #280/#282; #287/#288/#297; #289/#290/#299; #150; #296
- Source SHA: `main` `911c1cedf76dc6139f57b5d893d708b1a92245c6`
- Status: `BLOCKED / HUMAN_GATE`
- Review: required independent authorized collaborator on exact PR head
- This document is an evidence-only plan. It does not authorize execution, migration, grant changes, deployment or payment.

## Current staging facts from prior read-only inspection
- Neon `ola_staging` does not currently contain `human_gate_memberships` or `human_gate_approval_nonce_ledger`.
- The inspected `pg_policies` result was empty; inspected existing tables had RLS/FORCE RLS disabled.
- Existing `ola_runtime` write grants remain; no change was made.
- No DSN, secret, raw OIDC subject/token, personal data or customer payload is recorded here.
- These facts are a prior snapshot; an authorized operator must re-read them before a rehearsal. No state is inferred from this document.

## Preconditions — owner/admin only
1. Designate a distinct write-enabled CODEOWNER/reviewer; verify permission via GitHub. Issue #296 and #150 remain separate blockers.
2. Confirm a disposable, isolated PostgreSQL/Neon branch (not the shared staging branch), its owner, backup/restore point, expiry and cleanup procedure.
3. Provide a migration-review window and DB-owner authorization for the disposable target only.
4. Confirm external signer/key custody, OIDC issuer/audience/JWKS allowlist, step-up ACR/AMR policy and authorized human approver roster. OLA must not mint or store the private signing key.
5. Record redacted connection binding only (environment name and database/branch identity); never put DSN or credential material in the PR.

## Rehearsal sequence — not executed
### A. Read-only baseline
- Capture schema/migration version, table ownership, effective grants, RLS/FORCE RLS flags, policy definitions, triggers and indexes for the isolated target.
- Hash and sign/redact the evidence manifest; IGOR verifies the source SHA and artifact hashes independently.

### B. Disposable schema rehearsal
- Apply reviewed migrations only to the disposable target.
- Verify membership lookup is tenant-scoped and runtime role is read-only for membership.
- Verify approval nonce ledger is tenant-scoped, append-only, and supports atomic one-time consumption with worker claim.
- Verify policy and trigger contract; reject overprivileged runtime role.
- Restore the disposable branch from backup and repeat the checks; record RPO/RTO only from measured evidence.

### C. Negative and positive test matrix
- Wrong tenant/session, missing or invalid OIDC, wrong audience/issuer, stale step-up claims, requester self-approval, inactive/revoked membership, changed membership_version.
- Expired approval, stale evidence tip/source/policy, malformed or unsigned envelope, legacy API-key-only approval.
- Duplicate/replayed nonce and concurrent claims; exactly one claim succeeds.
- Cross-tenant reads/writes and tenant-scope A→B within a transaction fail closed.
- Runtime role cannot UPDATE/DELETE membership or nonce records; RLS denies cross-tenant access.
- Positive case is limited to a synthetic operation in the disposable environment and must not dispatch, charge, deliver or alter production/customer state.

### D. Operator-facing proof
- UI displays immutable operation digest, evidence IDs/hashes, current tip, source SHA, policy version/hash, tenant, requester/reviewer and expiry.
- Reviewer is current active execution_approver in the exact tenant; requester cannot approve.
- Signer remains outside OLA custody; approval is bound to exact immutable digest.
- Verify run.start→run.end, evidence chain, recovery, blast-radius limit and rollback.
- Capture sanitized test output, migration diff, DB policy/grant export, artifact manifest and SHA-256; IGOR verifies independently in a separate job/process.
- The signed application Human Gate remains PENDING until an authorized human completes it. CI cannot simulate it.

## Evidence package required for acceptance
1. Exact source/head SHA and exact CI runs.
2. Disposable target identity, backup/restore receipt and migration checksum.
3. Redacted schema/ACL/RLS/policy/trigger exports with SHA-256.
4. Negative/positive test results and concurrency/replay proof.
5. Runtime lifecycle and recovery metrics, source/image provenance where applicable.
6. Independent IGOR verification receipt and authorized human review.
7. Explicit status: DONE only when all required evidence is present; otherwise BLOCKED/UNKNOWN.

## Safety boundary
No mutation of shared Neon staging or production. No grant/role/RLS change, migration, payment, customer execution, deployment, secret access or public publication was performed.