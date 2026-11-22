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

Membership grants and revocation are **out-of-band admin operations**. The application resolver is read-only. No grant/revoke API or runtime write privilege is introduced here.

## Tests

SQLite-isolated tests cover current role resolution, tenant-claim mismatch, missing membership, role mismatch, revocation, invalid role, fingerprint-key ID binding and absence of raw subject storage.

## Not implemented

- No approval route or worker integration.
- No membership grant/revoke UI/API.
- No RLS or runtime DB privilege attestation for this table.
- No production DB migration, staging DB mutation, secret configuration or deployment.
- No signed approval creation or execution authorization.

**HUMAN_GATE:** before staging integration, the DB owner must approve the intended tenant registry target, grants and RLS design. Runtime must be restricted to read-only membership lookup. Independent review and exact-SHA CI are required.
