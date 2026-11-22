# CFR-2P-03 — OLA-owned tenant membership binding v1

**Candidate status:** additive database model + offline resolver and tests. Stacked on PR #280 exact head `0cee5de4d196451f6cc87d02629aae6260b08dec`. Not wired to an approval route or execution choke point.

## Binding contract

- The caller must first pass the token through the bounded OIDC verifier in CFR-2P-01.
- The verified tenant claim must be a canonical OLA UUID and equal the exact resource tenant selected by the application.
- The tenant claim is not role authority. The resolver computes a tenant-scoped HMAC fingerprint of the exact verified issuer/subject and looks up one OLA-owned membership row for that tenant, issuer, fingerprint key ID and fingerprint.
- Current role, membership version, active flag and revocation timestamp are loaded from the database. Missing, duplicate, inactive, revoked or role-mismatched membership fails closed.
- Raw OIDC subject and JWTs are not stored. The resolver returns only the principal ID, tenant, issuer, pseudonymous fingerprint, key ID, role and membership version.

## Database contract

The additive `human_gate_memberships` table has a unique subject-binding key, constrained role values, positive membership version and explicit active/revoked consistency. PostgreSQL migration is recorded as `ola_human_gate_membership_v1`; runtime schema verification requires the table and migration marker.

Membership grants and revocation are **out-of-band admin operations**. The application resolver is read-only. No grant/revoke API or runtime write privilege is introduced here. With `FORCE ROW LEVEL SECURITY`, a non-superuser administrative role must set the transaction-local `ola.human_gate_tenant_id` to the target tenant before an INSERT/UPDATE/DELETE. The same membership mutation trigger takes the tenant advisory lock used by runtime reads; the tenant scope cannot be switched inside one transaction. Runtime membership permissions remain SELECT-only.


## Tenant row isolation — PostgreSQL RLS candidate

The membership table is protected by:
- `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`;
- one exact `FOR ALL` policy whose `USING` and `WITH CHECK` predicates bind `tenant_id` to the transaction-local `ola.human_gate_tenant_id` setting;
- a server-side helper that uses PostgreSQL `set_config(..., true)`, so the tenant context is cleared at transaction end and does not leak through a pooled connection;
- runtime schema verification that rejects missing/duplicated/semantically different policies and rejects a runtime role that owns the table, is superuser, or has `BYPASSRLS`.

The resolver sets the scope only after the verified token tenant claim equals the canonical resource tenant, and retains an explicit tenant predicate in the SQL query. PostgreSQL tests exercise two tenant rows using the restricted runtime role: no scope returns zero rows, tenant A sees only A, tenant B sees only B, a primary-key lookup cannot cross tenants, a committed transaction does not leak its local setting, and the scope cannot switch A→B inside one transaction.

**Trust boundary:** a custom GUC is transaction context, not a cryptographic identity. A database role able to execute arbitrary SQL can call `set_config` itself. This RLS policy is a database-enforced guard against omitted tenant predicates and accidental cross-tenant queries; it does not independently contain arbitrary SQL execution under a compromised runtime credential. SQL injection prevention, least-privilege grants, non-owner/non-`BYPASSRLS` runtime role, and independent review remain required.

The RLS change is an additive migration candidate only. Runtime startup verifies the schema and fails closed; it does not run DDL. No production migration, grant change, or staging database mutation is authorized by this PR.

## Tests

SQLite-isolated tests cover current role resolution, tenant-claim mismatch, missing membership, role mismatch, revocation, invalid role, fingerprint-key ID binding and absence of raw subject storage.

## Not implemented

- No approval route or worker integration.
- No membership grant/revoke UI/API.
- No independent DB-owner approval of the RLS policy or production runtime-role/grant attestation.
- No production DB migration, staging DB mutation, secret configuration or deployment.
- No signed approval creation or execution authorization.

**HUMAN_GATE:** before staging integration, the DB owner must approve the intended tenant registry target, the exact RLS policy, admin grant/revoke procedure and runtime-role grants. Runtime must be restricted to SELECT-only membership lookup, must not own the table and must not be superuser or have `BYPASSRLS`. Independent review and exact-SHA CI are required.
