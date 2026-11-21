# OLA E2.2 — Tenant Security Architecture Decision

**Task:** `OLA-E2.2-FULL-CLOSURE-20261113`  
**Repository:** `krzysztofcieciwa07-ship-it/OLA`  
**Reference PR:** [#234](https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/234)  
**Protected baseline:** `36cd93c85f0f78caa007feb33b59cb1286a17b40`  
**Decision date:** 2026-11-13  
**Decision:** `ARCHITECTURE APPROVED WITH LIMITATIONS`  
**Implementation status at decision:** Not started in GitHub; no E2.2 branch or code commit created at this point.

> This is an architecture gate, not a security closure. It does not authorize production migrations, Railway changes, deployment, payment operations, or merge.

## 1. Executive decision

Select **C — transaction-bound trusted context established by restricted SECURITY DEFINER functions**.

The database must not authorize tenant access from `ola.tenant_id`, `ola.worker_mode`, or any other caller-settable custom GUC. Instead, a narrowly scoped database function validates authentication evidence against authoritative database state, derives the tenant ID itself, and stores the result in a protected transaction-local context. RLS policies call a database-owned predicate that reads that context.

The selected design uses separate evidence paths:

- API request: the existing high-entropy API-key fingerprint is checked against `api_keys`; tenant ID is derived from the matching row.
- Worker execution: `job_id` plus the database-issued claim token is checked against the outbox row and its lease; tenant ID is derived from that row.
- Stripe webhook: after application-level signature verification and authoritative Checkout Session retrieval, the database checks the exact stored `(order_id, stripe_session_id)` binding; tenant ID is derived from the order.

The context is stored in a temporary table created by a SECURITY DEFINER function, owned by the function/table owner, with `ON COMMIT DELETE ROWS`. The function verifies ownership and rejects a pre-created untrusted temporary relation. A transaction can establish only one tenant context. Commit and rollback clear the row. RLS does not consult the custom GUC.

This is approved with limitations because the isolated lab prototype blocks the demonstrated GUC bypass and passes the tested negative/positive paths, but the complete application migration, actual SQLAlchemy pool integration, key revocation/rotation, and independent review remain outstanding.

## 2. Recovery inventory — `PARTIALLY_EXECUTED`

### 2.1 GitHub

PR #234 is still OPEN / Draft / not merged. Its head is `e2/e2-1-postgres-contract-20261113` at the protected baseline SHA. Its base is `fix/postgres-tenant-rls-context-20261113` at `e799ec0424711337bf72ce417c6ffbac7b900af5`.

PR #234 history recovered and preserved:

1. `109288bb839d3f5a1e24ca58f62687740912118d` — verify worker search_path against explicit schema.
2. `f529312221fb1fcfc2d2229c4b7085889ca7bd77` — verify worker schema and restore complete function ACL.
3. `36cd93c85f0f78caa007feb33b59cb1286a17b40` — authenticate worker identity before schema diagnostics.

No commit, branch, review, or content change was made to PR #234 during this E2.2 recovery and prototype work.

### 2.2 Original Neon evidence

Recovered environment:

- Neon project: `ola-di-os-staging`, project ID `red-surf-47816548`.
- Region: `aws-eu-central-1`.
- PostgreSQL: `17.12 (14c6cec)`.
- Parent branch: `staging-ola-runtime-sha9485fd7a`, ID `br-long-silence-ba4v85h4`.
- Original isolated lab: `e2-2-tenant-bypass-lab-20261113`, ID `br-bold-meadow-bab8w35o`.
- Database: `e2lab`.
- Synthetic tenant fixtures only; no production credentials, production data, or parent application rows were queried.

The original lab branch was not modified by the architecture prototypes. Three child branches were created from it:

| Architecture | Branch | Neon branch ID | Purpose |
|---|---|---|---|
| A | `e2-2-architecture-a-20261113` | `br-lingering-shadow-baoafry7` | Per-tenant database identities |
| B | `e2-2-architecture-b-20261113` | `br-odd-pond-baj5xci3` | Signed tenant claim / HMAC prototype |
| C | `e2-2-architecture-c-20261113` | `br-young-frost-baki0a5h` | Database-verified transaction context |

### 2.3 Preserved artifacts

Recovered from the file library:

- `OLA-E2.2-TENANT-BYPASS-EVIDENCE.json`
- `OLA-E2.2-TENANT-BYPASS-SETUP.sql`
- `OLA-E2.2-TENANT-BYPASS-ATTACK.sql`
- `OLA-E2.2-TENANT-BYPASS-POOL-REUSE.sql`
- `OLA-E2.2-TENANT-BYPASS-SHA256SUMS.txt`

The SHA256 manifest lists the original report hash as `c29b4fbce46b6e7007493ce233a7e1959c5a42d1d244fdfd608b989dcac840d5`, but the report body itself was not recovered in this pass. The manifest hashes have not been recalculated from raw artifact bytes because the file service did not authorize raw-byte materialization. Therefore the original manifest is **recovered but not independently hash-verified** in this execution.

The original lab setup explicitly states it is a focused source-shaped reproduction, not a full replay of the OLA migration chain. It must not be represented as a full application integration test.

## 3. Confirmed vulnerability and scope

The original `ola_runtime` session had no `SUPERUSER` or `BYPASSRLS`, but had direct `SELECT` on `api_keys` and tenant tables, plus `INSERT`/`UPDATE` on tenant data. The RLS predicate trusted:

```sql
current_setting('ola.tenant_id', true)
```

The application populated that value with transaction-local `set_config`. Transaction-local scope prevents context leakage after transaction completion; it does not authenticate the value. Any SQL executed as `ola_runtime` can set the custom GUC itself.

The original attack evidence confirms:

- Cross-tenant SELECT succeeded after setting `ola.tenant_id` to tenant B.
- Cross-tenant INSERT succeeded.
- Cross-tenant UPDATE succeeded.
- DELETE was denied by the absence of a DELETE ACL, not by tenant RLS.
- INSERT/UPDATE attempts whose new row tenant did not match the forged GUC were denied by RLS `WITH CHECK`.
- `ola_authenticate_api_key(text)` was executable by runtime and returned identity metadata for a known synthetic key fingerprint; it did not establish a trusted database context.
- `ola_claim_checkout_jobs(integer,integer)` was not executable by runtime.
- A same-backend pool probe showed transaction-local GUC clearing after commit/rollback, while same-transaction spoofing still succeeded. The original evidence explicitly says this was not proof of OLA's SQLAlchemy pool behavior.

**Security conclusion:** the GUC is request scoping metadata, not an authenticated database identity. The confirmed attack is a real tenant-isolation bypass for anyone able to execute SQL as the shared `ola_runtime` database login.

## 4. Source audit findings

Reviewed at the protected baseline:

- `app/database.py`
- `app/tenant_context.py`
- `app/main.py`
- `app/models.py`
- `app/api_key_hashing.py`
- `app/paid_order_execution.py`
- `app/stripe_webhook.py`
- `scripts/migrate_postgres.py`
- `docs/postgres-runtime.md`

Relevant findings:

1. `app/database.py` installs the tenant context in the SQLAlchemy `after_begin` event by calling `set_config('ola.tenant_id', ..., true)`.
2. RLS policies use `current_setting('ola.tenant_id', true)` as the tenant selector.
3. `app/tenant_context.py` uses Python `ContextVar` values. These are useful for request scoping but do not establish an identity PostgreSQL can independently trust.
4. `identity_from_key()` calculates a keyed scrypt fingerprint and calls `ola_authenticate_api_key`; it then stores only `tenant_id` in the Python context. The fingerprint is not currently carried as transaction authentication evidence.
5. `ApiKey` currently contains `id`, `tenant_id`, `key_hash`, and `role`; no `revoked_at` or `expires_at` fields were found in the baseline model. API-key revocation and expiry are therefore not currently proven by the schema inspected.
6. Worker validation currently accepts a caller-supplied `tenant_id` and claim token, then establishes a tenant scope using that tenant ID before verifying the job. The database must derive tenant ID from the claim row instead.
7. Stripe webhook processing validates the event and retrieves the authoritative Checkout Session, but then sets the tenant GUC from session metadata. The database must independently bind the exact session ID to the stored order and derive tenant ID from that row.
8. Existing E2.1 contracts require exact role/table grants, dedicated function ownership, fixed `search_path`, SECURITY DEFINER, and no PUBLIC EXECUTE. E2.2 must preserve these controls and add the new context contract; it must not relax the verifier.
9. Existing `ola_authenticate_api_key` and `ola_claim_checkout_jobs` functions are SECURITY DEFINER with fixed `search_path=pg_catalog`; the migration owner is the table/function owner. The design retains this owner relationship for compatibility with the E2.1 contract.

## 5. Architecture comparison

| Criterion | A — per-tenant DB identities | B — cryptographically signed claims | C — DB-verified transaction context |
|---|---|---|---|
| GUC spoof resistance | Strong; identity comes from `session_user` | Strong if signature and replay rules are correct | Strong; RLS ignores GUC and checks protected context |
| Stolen shared runtime DB credential | Strong; shared runtime has no tenant data grants | Strong if signing key is external and unavailable to runtime | Strong if attacker lacks the API fingerprint, worker claim, or Checkout Session evidence |
| Compromised API process | Depends on credential broker and per-tenant credential isolation | Depends on independent signer validating API credentials | Can use credentials visible to the compromised process; cannot invent another tenant's valid evidence without obtaining that tenant's credential |
| Tenant identity source | Login role mapping | Signed claim from independent signer | Verified database row / opaque evidence |
| Pooling | Per-tenant pools or credential-aware pool routing | Shared pool with transaction challenge | Shared pool; context is transaction-local and cleared on commit |
| Worker compatibility | Requires per-tenant worker identity or a separate broker | Requires worker claim signing/verification | Natural fit: job ID + claim token derives tenant from job row |
| Webhook compatibility | Per-tenant credentials | Signed webhook/session claim | Exact stored order/session binding after Stripe verification |
| Operational complexity | High: role/secret/pool lifecycle per tenant | High: signer, KMS, key rotation, nonce/replay protocol | Moderate: narrow SQL functions and ContextVar evidence routing |
| Current prototype | Passed focused lab tests | Signature prototype exposed rollback replay limitation | Passed focused lab tests |

### A — prototype result

In child branch `br-lingering-shadow-baoafry7`, tenant A and tenant B were represented by separate PostgreSQL login roles. RLS used a protected role-to-tenant mapping keyed by `session_user`, not the custom GUC. Tenant A could set the GUC to tenant B and still read only tenant A. Cross-tenant INSERT was denied by RLS; cross-tenant UPDATE affected zero rows. Tenant A could not `SET ROLE` to tenant B, and shared `ola_runtime` lost direct table access.

**Result:** `LAB_REPRODUCED` for the focused API-table isolation case. Not selected because it requires per-tenant DB credential issuance, storage, rotation, pool routing, and a separate worker strategy. It remains a valid stronger-isolation option if the threat model later requires containment of a broadly compromised application process.

### B — prototype result

In child branch `br-odd-pond-baj5xci3`, `pgcrypto` HMAC claims were validated by a SECURITY DEFINER function. A valid synthetic claim established tenant context despite an opposite GUC. A tampered tenant claim was rejected. Replaying a claim after a committed transaction was rejected by the nonce table.

A forced subtransaction rollback exposed a critical flaw: because nonce consumption is in the same transaction, rollback also rolls back nonce consumption; the same signed claim could then be replayed. This does not meet the required rollback/replay guarantee. A production B design would need a transaction-bound challenge signed by an independent authentication service/KMS, or an independently committed nonce-consumption authority. Neither signer nor transaction-bound challenge was available or validated in this execution.

**Result:** `LAB_REPRODUCED_WITH_LIMITATION`; not selected for this implementation.

### C — prototype result

In child branch `br-young-frost-baki0a5h`, the focused RLS policies were changed to call `ola_tenant_context_matches(...)`, not read a GUC. The setter functions derived tenant ID from authoritative evidence and inserted a single row into a protected temporary table with `ON COMMIT DELETE ROWS`.

Observed tests:

- GUC spoof without context returned no tenant rows.
- Valid API-key fingerprint A established tenant A even after setting the GUC to B; only A rows were visible.
- Invalid API-key evidence was rejected (`42501`).
- A second tenant context in the same transaction was rejected (`42501`).
- Cross-tenant INSERT was rejected by RLS (`42501`).
- Cross-tenant UPDATE affected zero rows.
- Reassigning tenant A's row to tenant B was rejected by RLS `WITH CHECK` (`42501`).
- Cross-tenant DELETE affected zero rows when a temporary test-only DELETE grant was added; that grant was revoked immediately afterward.
- Direct `SELECT` on `api_keys` was denied, while `ola_authenticate_api_key` continued to return the expected identity metadata.
- Direct `SELECT` on the temporary context table was denied.
- A runtime-precreated fake `ola_tenant_context` temp table was rejected as untrusted (`42501`).
- Worker claim B established B context despite a forged tenant A GUC.
- Stripe session B established B context despite a forged tenant A GUC; an incorrect session/order binding was rejected.
- Two parallel runtime sessions, one using A evidence and one B evidence, saw only their respective tenant rows despite opposite GUC values.
- Two sequential Neon connector transactions reused backend PID `1460`; after the first transaction committed, the second transaction had no context and returned no rows. This verifies the PostgreSQL temp-table transaction behavior on the Neon connector, not the actual OLA SQLAlchemy pool.
- Runtime could not `SET ROLE ola_migrator` (`42501`).

The prototype's context setter stores only a non-secret evidence identifier in the temp table (API key row ID, job ID, or order ID), not the raw API key fingerprint or claim token. The fingerprint/token/session ID is used only to verify the evidence.

**Result:** `LAB_REPRODUCED` for the focused API, worker, and Checkout Session evidence paths. This is the selected architecture, subject to the limitations and implementation requirements below.

## 6. Selected design contract

### 6.1 Database functions

Implement narrow SECURITY DEFINER functions, all with:

- fixed `SET search_path = pg_catalog`;
- fully qualified application table references;
- owner equal to the appropriate table owner, preserving E2.1 ownership rules;
- `REVOKE ALL ... FROM PUBLIC`;
- explicit EXECUTE grants only to `ola_runtime` where required;
- no grant options and no unexpected grantees;
- explicit validation that `session_user` is the expected runtime login;
- no caller-supplied tenant ID accepted as authority.

Required functions:

1. `ola_prepare_tenant_context()` — create or verify the definer-owned temp table, reject a pre-created untrusted relation, and reject a second context in the same transaction.
2. `ola_establish_api_key_context(p_key_hash)` — validate the fingerprint against `api_keys`, reject revoked/expired keys, derive tenant ID and API-key row ID, and establish context.
3. `ola_establish_worker_context(p_job_id, p_claim_token, p_stale_after_seconds)` — validate claim token, lease, status, and attempt count against the job row; derive tenant ID from the row.
4. `ola_establish_checkout_context(p_order_id, p_session_id)` — validate exact stored order/session binding; derive tenant ID from the order row.
5. `ola_tenant_context_matches(p_tenant_id)` — SECURITY DEFINER predicate that returns true only when the current backend's protected transaction-local context matches the row tenant.

The temporary context table must:

- be created by the trusted function owner, not the runtime login;
- be verified by catalog owner metadata before use;
- contain only tenant ID, evidence kind, and a non-secret evidence row ID;
- use `ON COMMIT DELETE ROWS`;
- allow exactly one context per transaction;
- be inaccessible directly to runtime and worker roles;
- fail closed if absent, malformed, or pre-created by the runtime.

### 6.2 RLS and grants

- Replace all GUC-based tenant predicates on every tenant table with the protected predicate.
- Keep both `USING` and `WITH CHECK` tenant boundaries.
- Keep RLS enabled on all tenant tables.
- Keep the existing exact runtime DML matrix except revoke direct `SELECT` on `api_keys`; API-key lookup remains through the narrow SECURITY DEFINER function.
- Keep worker direct table privileges absent; worker claim remains a separate database capability.
- Do not grant DELETE merely to make a test pass. DELETE tests may use a temporary lab-only grant and must revoke it immediately.
- Preserve the E2.1 role restrictions: `LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION`, no runtime/worker membership in other roles, no grants of runtime/worker roles to other principals, and both `session_user` and `current_user` checks.
- Keep the migration/table owner separate from API and worker credentials. The owner is privileged and must never be configured as an application DSN.

### 6.3 Application context lifecycle

Replace tenant-ID-only authority in `ContextVar` with typed evidence:

- API request context: tenant ID for application logic plus API-key fingerprint for database re-verification.
- Worker context: job ID and claim token; tenant ID is derived by PostgreSQL.
- Stripe context: order ID and Checkout Session ID; tenant ID is derived by PostgreSQL after the application has verified the Stripe signature and retrieved the authoritative session.

The SQLAlchemy `after_begin` hook must call the matching database setter on every new PostgreSQL transaction. It must not call `set_config('ola.tenant_id', ...)` as an authorization mechanism. The application may continue setting a diagnostic GUC if desired, but no RLS policy may consume it.

SQLite behavior remains compatible and may continue using application tenant scope because SQLite does not provide PostgreSQL RLS. PostgreSQL worker and webhook paths must not fall back to tenant-ID-only context.

### 6.4 API-key lifecycle

The baseline `ApiKey` schema has no revocation or expiry fields. Before E2.2 closure, add a minimal lifecycle contract:

- `revoked_at` nullable timestamp;
- `expires_at` nullable timestamp;
- authentication rejects revoked or expired keys inside the database function;
- rotation creates a new key row and revokes the old key without an overlap unless explicitly configured;
- raw API keys and fingerprints are never logged;
- add positive/negative tests for active, revoked, expired, and rotated keys.

The fingerprint is a bearer-equivalent secret. It must remain in memory only long enough to establish each transaction context and must not be persisted in the temp table or logs.

## 7. Threat model and residual risk

| Threat | Mitigation / verification requirement | Current status / residual risk |
|---|---|---|
| Compromised API process | Require per-request evidence; no tenant-ID setter; redact keys; isolate request handling; rate-limit auth; test what a compromised process can do with one tenant's credential | A compromised process can use credentials it currently handles. It must not gain arbitrary cross-tenant access without another tenant's valid evidence. Residual risk remains. |
| Stolen `ola_runtime` DB credential | No direct `api_keys` SELECT; no context-table access; GUC ignored; setters require valid key/claim/session evidence | Focused lab tests passed. Full production configuration not verified. |
| Direct SQL under runtime | Same protected RLS predicate on every tenant table; no direct context mutation | Focused lab tests passed. Full table inventory pending. |
| Arbitrary GUC manipulation | Remove GUC from all RLS expressions | Focused lab tests passed. |
| Forged tenant ID | Setter APIs accept evidence, not tenant ID; database derives tenant from authoritative rows | API/worker/Stripe prototype paths passed. |
| SECURITY DEFINER misuse | Fixed search_path, explicit owner, fully qualified names, narrow SQL, PUBLIC revoked, exact ACL assertions | Prototype metadata checked; complete source migration and negative ACL suite pending. |
| Role escalation | NOINHERIT, no membership, no SET ROLE path, verify both session/effective identities | Runtime `SET ROLE ola_migrator` denied. Lab still shows `ola_migrator` as a member of runtime/worker; runtime itself has no membership in a privileged role. Fresh production role provisioning must remove all memberships in both directions. |
| Connection-pool context leakage | Temp table `ON COMMIT DELETE ROWS`, one context per transaction, fail closed | Same backend PID reused across two Neon connector transactions; actual SQLAlchemy pool not yet tested. |
| Concurrent tenant requests | Separate transaction context per backend/transaction; parallel tenant probes | Two parallel Neon connector sessions returned only their respective tenant rows. SQLAlchemy concurrency test pending. |
| Worker cross-tenant access | Derive tenant from job row after verifying claim token and lease; worker has no direct tenant-table grants | Focused worker context test passed. Full worker execution test pending. |
| Context replay / switching | One context per transaction; temp rows cleared on commit/rollback; claim lease checked on each transaction | Same-transaction switch rejected; commit reuse test passed. Full rollback/exception/pool test pending. API keys remain reusable credentials until revoked/expired. |
| API-key revocation and rotation | Add DB-enforced revoked/expiry fields and test key replacement | Not implemented in baseline; `NOT_VERIFIED`. |
| Partial migration / recovery | Versioned atomic migration, fail-closed verifier, explicit rollback/recovery script | Not tested; `NOT_VERIFIED`. |
| Information leakage | Generic DB errors, no key/token in context rows/logs, redaction tests | Not fully tested; `NOT_VERIFIED`. |

## 8. Migration and rollback strategy

### Migration

1. Create a new versioned migration, for example `ola_tenant_trusted_context_v1`.
2. Add API-key lifecycle columns additively.
3. Create the trusted context functions and their ACLs before changing RLS policies.
4. Update application code to establish typed evidence on every PostgreSQL transaction.
5. Replace GUC-based policies on all tenant tables in one transaction.
6. Revoke direct `SELECT` on `api_keys` from `ola_runtime` only after the function path is ready.
7. Run the verifier inside the migration transaction; commit only if all owner, ACL, role, RLS, and function checks pass.
8. Record the migration identity and schema snapshot in the evidence package.

### Rollback

A rollback must **never restore GUC-based authorization**. Re-enabling the old GUC predicate would reintroduce the confirmed bypass. If the new application version cannot operate against the migrated schema, the safe response is to fail closed and disable PostgreSQL runtime traffic until a compatible fix is available. A partial migration must roll back atomically. A committed migration is reversed only by a reviewed forward-fix or by a controlled restore to a known-safe snapshot; do not downgrade the security boundary.

## 9. Required implementation and verification gates

Before E2.2 closure, the separate E2.2 branch must contain:

- migration and rollback/recovery scripts;
- updated database verifier and exact ACL matrix;
- typed context lifecycle in `tenant_context.py`;
- updated SQLAlchemy `after_begin` hook;
- API-key, worker-claim, and Stripe Checkout evidence setters;
- GUC-free RLS policies for every tenant table;
- API-key revocation/expiry and rotation contract;
- security regression tests for all CRUD operations, spoofing, forged evidence, context switching, commit/rollback, pool reuse, concurrency, worker claims, webhook binding, role escalation, and SECURITY DEFINER ACLs;
- E2.1 PostgreSQL contract regression tests unchanged in strength;
- performance measurements and observability/redaction tests;
- recovery/partial migration tests.

The actual OLA SQLAlchemy pool must be tested against PostgreSQL, not inferred from a Neon SQL connector probe. Run exact commands and record exact outputs against the final candidate SHA.

A reviewer other than the implementation author must independently inspect the migration, function ownership/ACLs, RLS policies, negative tests, positive workflows, pool/concurrency tests, and independently reproduce the original cross-tenant attack. If that reviewer is unavailable, record `NOT_VERIFIED` and do not close E2.2.

## 10. Evidence classification at architecture gate

| Claim | Classification |
|---|---|
| Original GUC cross-tenant bypass | `LAB_REPRODUCED` (preserved original evidence) |
| Baseline source uses caller-controlled GUC for RLS | `CODE_REVIEWED` |
| Architecture A role-based prototype | `LAB_REPRODUCED` |
| Architecture B HMAC prototype and rollback replay flaw | `LAB_REPRODUCED` |
| Architecture C API/worker/Stripe context prototype | `LAB_REPRODUCED` |
| Actual OLA SQLAlchemy pool behavior under new design | `NOT_VERIFIED` |
| Full OLA migration chain on a production-shaped clone | `NOT_VERIFIED` |
| API-key revocation and rotation | `NOT_VERIFIED` |
| Full performance and observability measurements | `NOT_VERIFIED` |
| Independent security review | `NOT_VERIFIED` |
| Original SHA256 manifest recalculation from raw bytes | `NOT_VERIFIED` |

## 11. Architecture gate result

**`ARCHITECTURE APPROVED WITH LIMITATIONS`**

C is selected because it directly removes the trust placed in a caller-settable GUC, independently validates the evidence in PostgreSQL, supports API/worker/webhook flows, preserves the E2.1 function-owner and ACL contract, and passed focused negative and positive lab probes. A is a valid alternative but carries substantially greater per-tenant credential and pool-routing complexity. B is not accepted until a transaction-bound challenge and rollback-safe replay mechanism are independently implemented and tested.

The limitations above are mandatory implementation and verification work, not waivers. E2.2 remains open. No production action is authorized.

## 12. Next authorized action

Create a separate E2.2 branch from the protected baseline SHA, add this architecture decision, and implement the minimum complete C design with additive migration, fail-closed rollback behavior, and preserved E2.1 tests. Create/update a Draft PR only. Do not modify or merge PR #234. Stop at E2.2; do not start E2.3.