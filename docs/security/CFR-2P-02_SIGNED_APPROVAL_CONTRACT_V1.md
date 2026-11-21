# CFR-2P-02 — Signed Approval Record v1 and OIDC subject binding

**Date:** 2026-11-21  
**State:** design + offline contract primitives + CI test candidate. Not wired to app routes, ORM, migrations, workers, signer, Railway or production. No real approval was created.

## 1. Why CFR-2P-02 is separate from CFR-2P-01

PR #276 adds a bounded OIDC RS256 verifier. It returns `(issuer, subject, tenant_id)`. A valid token proves possession of an issuer-signed identity assertion with expected claims; it does **not** establish that the subject is a member of the referenced OLA tenant, has an OLA role, or may approve a specific effect.

Main currently stores checkout requester / approver / report reviewer as `ApiKey.id` references and checks the API-key role in `app/order_approval.py` and `app/report_review.py`. API keys remain technical credentials. They are not a durable human principal identity.

CFR-2P-02 defines the mapping and approval contract without changing those routes or tables.

## 2. Identity mapping

### Verified input

The only accepted identity source is output from the verifier in PR #276 after:
- exact issuer and audience validation;
- RS256 signature verification against bounded allowlisted JWKS;
- required `iss`, `aud`, `exp`, `iat`, `sub` validation;
- bounded token/JWKS size, no redirects and no arbitrary JWKS host.

Do not accept `role`, `groups`, `tenant_role`, `is_admin` or similarly named JWT claims as authorization on their own.

### Principal mapping candidate

Resolve the verified `(issuer, subject)` against an OLA-owned membership registry scoped by the resource tenant. The lookup returns an internal `principal_id`, an active `tenant_id`, an explicitly granted OLA role, membership version, and revocation state.

Proposed stable key:
- `tenant_id`
- exact `issuer`
- `subject_fingerprint` (tenant-scoped HMAC-SHA-256 over a domain-separated, length-framed tuple)
- `fingerprint_key_id`
- `membership_version`

Do not persist raw OIDC subject, access token, refresh token, or ID token in Evidence. The pure function in `app/approval_contract_v1.py` derives the fingerprint; it deliberately accepts no role or group claim.

Fingerprint key rules:
- dedicated identity-fingerprint key, minimum 32 random bytes;
- key lives in a secret manager/KMS, not repo, DB dump, evidence or CI output;
- separate from API-key pepper, Evidence V4 keyring, Stripe secret and Ed25519 approval signing key;
- record key ID and rotation policy; do not silently rewrite old fingerprints during rotation;
- tenant in the HMAC input prevents simple cross-tenant linkability.

### Authoritative membership and roles

The future membership store is the source of role authority. It must support explicit grants, revocation, membership version and audit provenance. A person can have several roles in different tenants; role evaluation must always bind to the target tenant and the exact resource.

Minimum roles:
- `requester` — may create a request; cannot approve it;
- `execution_approver` — may approve exactly one paid-order execution effect;
- `report_reviewer` — may independently approve a completed report for release to the original requester.

The role is loaded from OLA's trusted membership state at decision time. The JWT verifier does not mint or upgrade roles. Legacy API keys do not become human principals by implication.

## 3. Signed Approval Record v1

Schema: `schemas/signed-approval-record-v1.schema.json`  
Implementation of pure contract primitives: `app/approval_contract_v1.py`

### Envelope

The envelope contains exactly:
- `payload` — all decision-relevant data;
- `signature` — algorithm `Ed25519`, `key_id`, base64url signature value.

Only payload is signed. The signature envelope is never included in the payload bytes.

### Required payload semantics

The payload binds:
- schema version, approval UUID, tenant UUID, operation UUID and one-use nonce;
- one exact action and resource ID, request digest and expected effect/target digest;
- disposition `ALLOW | REFUSE | UNRESOLVED | INCOMPARABLE`;
- `effect_authorized`, which is true **only** for `ALLOW`;
- execution observation `NOT_STARTED` at approval time;
- author, final reviewer and any prior approver identities, including internal principal IDs, tenant, issuer, pseudonymous subject fingerprint, fingerprint key ID and membership version;
- reviewer step-up authentication metadata (`auth_time`, `acr`, `amr`, session fingerprint);
- exact policy version + SHA-256;
- source commit SHA, ordered Evidence record references and Evidence tip hash;
- bounded reason, issue time and expiry;
- operational, epistemic and remedial closure all still `OPEN`.

### Supported effects

1. `EXECUTE_PAID_ORDER` for one `checkout_order`:
   - reviewer role must be `execution_approver`;
   - reviewer must differ from author;
   - the authorized effect is only `QUEUE_SINGLE_EXECUTION` for the same order ID and bound digest;
   - no deployment or production authority is implied.

2. `APPROVE_CUSTOMER_REPORT` for one `customer_report`:
   - reviewer role must be `report_reviewer`;
   - reviewer must differ from both requester and execution approver;
   - exactly one prior execution approver is bound;
   - the only effect is `RELEASE_REPORT_TO_ORIGINAL_REQUESTER` for the same report ID and digest.

No generic `execute arbitrary tool` approval exists in v1.

## 4. Canonical bytes and cryptographic boundary

The pure implementation defines:
- domain prefix `OLA-SIGNED-APPROVAL\0v1\0`;
- deterministic UTF-8 JSON with recursively sorted object keys and compact separators;
- NFC-only strings;
- safe interoperable integer bound (2^53−1);
- no floats, NaN, infinities or implementation-specific values;
- bounded payload depth, node count and encoded size;
- explicit length framing for identity HMAC material.

The Ed25519 private key is not implemented in this slice. Later signing must use a dedicated protected signer/HSM/KMS or reviewed equivalent. The verifier must pin allowed signer key IDs/public keys and verify the exact domain-separated bytes. Never store a private signing key in the evidence database.

## 5. Human-in-the-loop execution protocol

A real Human Gate must be interactive and human-originated:
1. Show the exact request, target, amount/resource, digest, evidence tip, source commit and exact effect before the person approves.
2. Authenticate the reviewer through the configured identity provider and require step-up authentication meeting the approved `acr`/`amr` policy. `auth_time` must be recent.
3. Independently resolve current tenant membership and role from OLA's trusted membership registry.
4. Reject self-approval and reject reviewer reuse across the execution/report-review separation-of-duties boundary.
5. Create a short-lived record (maximum five minutes), with a cryptographically random nonce and exact operation/resource binding.
6. Verify current signature, policy, membership, source binding, evidence chain/tip and target state at the effect boundary.
7. Atomically consume the nonce and create the single outbox job in the same protected transaction. A duplicate/replayed nonce or operation is rejected.
8. Record execution as `NOT_STARTED` in the approval. Only the executor can append observed `SUCCEEDED`/`FAILED`/blocked evidence afterwards.
9. An approval authorizes only the exact effect stated. It does not authorize deployment, migration, production configuration or any additional action.

CI, a workflow, an LLM, a synthetic fixture or this contract test suite must never create a real approval. The test signature fixture in `tests/test_approval_contract_v1.py` exists only to validate JSON Schema shape; it is not cryptographic and is never submitted to an application.

## 6. Replay, expiry and revocation

The offline contract constrains a maximum five-minute TTL and a maximum five-minute reviewer authentication age. These checks are not sufficient for execution by themselves.

The future stateful verifier must additionally:
- atomically claim/consume nonce once, scoped by tenant + operation + approval;
- reject duplicate approval IDs and duplicate execution outbox jobs;
- re-check current membership and current role at time of execution, not just signing;
- reject revoked/disabled principals, revoked membership versions and superseded policy;
- reject stale evidence tips, source SHA mismatch, changed target digest and policy digest mismatch;
- fail closed on legacy orders without proven author identity;
- preserve append-only history on correction/revocation.

## 7. Test matrix

The candidate suite validates:
- Draft 2020-12 schema compilation and both supported action shapes;
- deterministic serialization, domain separation and independently recomputed SHA-256;
- rejection of float, oversized integer, non-NFC text and signature-in-payload;
- tenant-scoped subject fingerprints and no role derivation from identity;
- no self-approval and no reviewer reuse across report separation-of-duties;
- `REFUSE`, `UNRESOLVED` and `INCOMPARABLE` cannot authorize an effect;
- approval cannot claim that execution already happened or that any closure has occurred;
- TTL, auth age, tenant binding, sequence ordering and final evidence-tip equality;
- strict JSON Schema additional-property and Ed25519 envelope constraints.

CI adds `requirements-contracts.txt` for JSON Schema validation only. Dockerfile installs `requirements.txt`, not `requirements-contracts.txt`; this keeps the validator outside the production image.

## 8. Not implemented / later gates

- No SQLAlchemy identity/membership model or migration.
- No route integration into checkout, NINA, paid-order or report-review APIs.
- No OIDC provider configuration, JWKS request or secrets in Railway.
- No private Ed25519 signer or KMS key.
- No durable nonce table or atomic nonce consumption.
- No real Human Gate, approval, execution or customer delivery.
- No permission, role or branch-protection changes.
- No DB or Railway writes.

Required later sequence: independent design/security review → membership model and migration design → disposable PostgreSQL contract and negative tests → signer/key-custody review → API/broker integration → isolated staging DB binding evidence → real human acceptance test → separately authorized production rollout. No stage may be skipped because schema tests pass.
