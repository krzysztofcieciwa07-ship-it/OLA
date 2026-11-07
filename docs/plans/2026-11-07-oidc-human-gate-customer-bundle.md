# OLA Human Identity i Customer Bundle — Implementation Plan

> **Execution status (2026-11-07):** implementation changes are present in PR #190, but CI for the current head has not completed. Do not treat this plan as a test report or production acceptance.

- PR: [#190](https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/190), Draft, stacked on PR #189.
- Current verified branch head at last check: `098e5970f2cf48ca78309f9a945f74c5361da2d1`. Newer commits may supersede this SHA; read the branch ref before acting.
- Branch base: PR #189 head `8e56b33df9a3e2806f3709fca90b07e4e595d28f`.
- CI state for that head: 19 checks queued, zero completed; the latest subsequent commit has not yet completed CI.
- No merge, production deploy, IdP, HR/SCIM, KMS/HSM, RFC 3161 TSA or production object store configuration has been performed.
- Replit reviewer HTML remains unintegrated; its source/API contract has not been independently verified against this branch.
- Current default app state deliberately has `customer_bundle_runtime = None`; the bundle issue/download path returns 503 until explicit dependencies are injected.

## Implementation already present in PR #190

- Human Identity: OIDC sessions, persistent tenant policy latch, HR-backed person refs, SoD and dual-control role change routes.
- Production profile is derived from the public HTTPS origin; a conflicting sandbox environment label cannot downgrade Human Gate or bundle issue/download.
- Paid decision reports can embed `order_id` before computing the report digest.
- Customer bundle: deterministic dual-signed Ed25519 archive, independent trusted-key check, signer public-key alias rejection, bundle identity/version/created/expiry bound into the signed manifest, offline verifier and CLI.
- Bundle issue service re-checks the approved report digest, exact approval Evidence, full tenant chain, unique execution completion record and current signing tip before persistence.
- Production requires independent IGOR/provenance providers and RFC 3161 verifier/provider. Missing services fail closed.
- Recipient grants and per-transfer attempts are separate; explicit ACK is a separate Evidence event and is not interpreted as report comprehension.
- Recipient authentication has a provider-neutral interface. OIDC is the current adapter; WebAuthn/passkey is not implemented or configured.
- Download re-verifies the ZIP against an independent trust store and database bundle metadata before streaming; expired packages are refused even when their signatures remain cryptographically valid.

## Verification limitations

- GitHub Actions for the current branch head were pending/queued at the last check. No claim of green CI is made.
- PostgreSQL integration jobs may explicitly skip real integration tests when `OLA_TEST_POSTGRES_URL` is absent; a contract job alone is not a live database proof.
- The code has not yet been run against a real tenant IdP/HR mapping, separate remote signer services, timestamp authority or durable production storage.
- End-to-end customer delivery and real payment receipt remain UNVERIFIED.

---


> **For agentic workers:** Execute task by task. Do not merge PR #189 or deploy production.

**Goal:** Zastąpić API-key identities dla ludzkich decyzji tożsamością federacyjną opartą o HR person key i dostarczać klientowi pakiet dowodowy z niezależnym podpisem IGOR oraz podpisem OLA.

**Architecture:** Provider-neutral Human Identity z OIDC jako pierwszym adapterem operatorów, monotoniczna zapadka polityki tenanta, SoD na HR-backed person_key i dual-control admin. Pakiet klienta ma oddzielne podpisy IGOR/OLA, zewnętrzny proof czasu i offline verifier; lifecycle pakietu, grantów i prób transferu jest rozdzielony.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.1, PostgreSQL/SQLite, Authlib 1.9.5, cryptography 50.0.2, pytest, GitHub Actions. KMS, IdP, HR/SCIM, TSA i storage pozostają zewnętrznymi bramkami.

## Global Constraints

- Baza: PR #189 head 8e56b33df9a3e2806f3709fca90b07e4e595d28f. Branch potomny PR #189; nie zmieniać jego head, nie scalać PR #189 ani nie tworzyć PR do main w sposób wciągający jego niezatwierdzone commity.
- Replit branch/HTML jest materiałem referencyjnym, nie źródłem API ani backendu, dopóki nie potwierdzimy źródłowego commitu i runtime.
- Nie backfillować historycznych API keys do Human Principal.
- OIDC_REQUIRED jest monotoniczne. Po aktywacji nie ma fallbacku do API key, flagi środowiskowej ani rollbacku auth.
- SoD porównuje HR/SCIM person_key, nie tylko issuer+subject/e-mail. Brak wiarygodnego person_key blokuje akcje krytyczne.
- Administrator nie może sam nadać sobie krytycznej roli/grantu. Zmiany krytyczne wymagają dual-control dwóch różnych person_key i Evidence.
- Evidence zawiera pseudonimowe principal_ref/person_ref; issuer/subject i mapowanie HR pozostają w mutowalnym identity store.
- Bundle, recipient grant i delivery attempt to odrębne encje i maszyny stanów.
- Klucze Ed25519 IGOR i OLA muszą mieć niezależne custody i security principals. Dwa PEM-y w jednym procesie nie są kryptograficzną niezależnością.
- manifest/signature/attestation control files nie wchodzą do własnej listy hashy. ZIP ma deterministyczne entry order, mtime i permissions.
- Filtrowany order-evidence NDJSON jest podpisaną atestacją wyciągu, nie możliwością odtworzenia pełnego tenant chain.
- Produkcyjne GO wymaga realnego IdP, HR mapping, MFA, oddzielnych signer services/KMS, TSA/transparency, szyfrowanego storage, provenance, restore i realnego klienta. Mocki nie wystarczą.
- TDD: każda zmiana zachowania zaczyna się od testu z zaobserwowanym red, następnie green i integracja. Brak uruchomienia testów musi być jawnie podany.

---

### Task 1: Monotoniczna polityka Human Gate i schemat tożsamości

**Files**
- Modify: app/models.py
- Modify: app/database.py
- Create: app/human_identity/policy.py
- Create: tests/test_human_identity_policy.py
- Modify: tests/test_postgres_integration.py
- Modify: docs/postgres-runtime.md

**Interfaces**
- set_tenant_human_gate_mode(tenant_id, actor_ref, reason, target_mode) -> dict
- require_human_identity_mode(tenant_id, deployment_profile) -> str
- TenantIdentityPolicy: tenant_id, human_gate_mode, changed_at, changed_by_ref, reason
- Legal transitions: LEGACY_API -> OIDC_REQUIRED only.

- [ ] **Step 1: Add failing behavioral tests.**
Test legacy compatibility only for non-production; production missing/legacy policy returns BLOCKED; transition to OIDC_REQUIRED succeeds; repeated activation is idempotent; downgrade, unknown mode, missing actor or reason is rejected; blocked downgrade leaves state unchanged and appends pseudonymous human.identity_policy_downgrade_blocked Evidence.

- [ ] **Step 2: Verify red.**
Run pytest -q tests/test_human_identity_policy.py.
Expected: the test reaches the new public seam and fails on the missing monotonic policy behavior, not on test setup or collection.

- [ ] **Step 3: Implement minimum behavior.**
Create the one-row-per-tenant policy table. Change runs inside begin_write_transaction under tenant evidence lock, atomically updating policy and append-only Evidence. Production rejects missing policy or any mode other than OIDC_REQUIRED. No environment flag can weaken a locked policy. Add migration version ola_human_identity_policy_v1 and required schema verification. SQLite gets additive migration; PostgreSQL DDL remains explicit migration-role only.

- [ ] **Step 4: Verify green.**
Run pytest -q tests/test_human_identity_policy.py.
Expected: all positive, idempotent, downgrade and production fail-closed cases pass.

- [ ] **Step 5: Integration checks.**
Run pytest -q tests/test_paid_order_approval.py tests/test_paid_order_report_review.py tests/test_postgres_integration.py.
Expected: existing LEGACY_API sandbox tests stay compatible; PostgreSQL suite runs or is explicitly skipped only when OLA_TEST_POSTGRES_URL is absent.

- [ ] **Step 6: Commit.**
git add app/models.py app/database.py app/human_identity/policy.py tests/test_human_identity_policy.py tests/test_postgres_integration.py docs/postgres-runtime.md
git commit -m "feat(identity): add monotonic Human Gate policy"

### Task 2: OIDC operator identity and server-side sessions

**Files**
- Create: app/human_identity/oidc.py
- Create: app/human_identity/sessions.py
- Create: app/human_identity/principals.py
- Modify: app/models.py
- Modify: app/database.py
- Modify: requirements.txt
- Modify: app/main.py
- Create: tests/test_oidc_human_identity.py
- Create: tests/test_human_identity_sessions.py

**Interfaces**
- begin_oidc_login(request, tenant_id) -> RedirectResponse
- complete_oidc_login(request, tenant_id) -> RedirectResponse
- resolve_human_session(cookie_value) -> HumanPrincipalContext
- HumanPrincipalContext: tenant_id, principal_ref, person_ref, roles, auth_time, mfa_verified
- OIDC issuer/discovery/JWKS are allowlisted by tenant configuration and never read from request input.

- [ ] **Step 1: Add failing protocol/session tests.**
Valid local OP fixture authorization-code + PKCE S256 succeeds. Reject wrong state, nonce, issuer, audience, azp, expired ID token, unsupported algorithm, changed JWKS key, replayed callback, missing person_key, unknown membership, suspended principal, logout replay, expired session and CSRF failure. Assert tokens/code_verifier/full claims are not stored in Evidence or logs. auth_time is required only for high-risk step-up.

- [ ] **Step 2: Verify red.**
Run pytest -q tests/test_oidc_human_identity.py tests/test_human_identity_sessions.py.
Expected: missing adapter/session behavior fails through explicit test assertions, not collection errors.

- [ ] **Step 3: Implement provider adapter.**
Pin Authlib 1.9.5. Use Authlib Starlette OIDC client, explicit allowed ID-token algorithms and server-side transaction/session storage for state, nonce and code_verifier. Cookie contains only an opaque random session ID; database stores only its hash plus minimal session fields. Callback validates exact issuer/audience/signature/nonce/state and never auto-provisions membership. person_key comes only from configured HR/SCIM mapping or approved signed claim. Missing mapping blocks privileges.

- [ ] **Step 4: Verify green.**
Run pytest -q tests/test_oidc_human_identity.py tests/test_human_identity_sessions.py.
Expected: valid fixture succeeds; malformed, unknown and replay cases fail closed.

- [ ] **Step 5: Integration checks.**
Run pytest -q tests/test_paid_order_approval.py tests/test_paid_order_report_review.py tests/test_nina_workflow_api.py.
Expected: machine routes remain unchanged; API-key Human Gate attempts for OIDC_REQUIRED tenants are denied.

- [ ] **Step 6: Commit.**
git add app/human_identity app/models.py app/database.py app/main.py requirements.txt tests/test_oidc_human_identity.py tests/test_human_identity_sessions.py
git commit -m "feat(identity): add OIDC operator sessions"

### Task 3: HR-backed SoD, dual-control membership and Human Gate binding

**Files**
- Create: app/human_identity/membership.py
- Modify: app/order_approval.py
- Modify: app/report_review.py
- Modify: app/main.py
- Modify: app/models.py and app/database.py
- Create: tests/test_human_identity_sod.py
- Modify: tests/test_paid_order_approval.py and tests/test_paid_order_report_review.py

**Interfaces**
- request_role_change(tenant_id, target_principal_ref, requested_role, actor_context, reason) -> change_id
- approve_role_change(change_id, actor_context, reason) -> dict
- assert_distinct_humans(contexts) compares tenant-scoped person_ref values.
- Human Gate routes consume verified HumanPrincipalContext for OIDC_REQUIRED tenants.

- [ ] **Step 1: Add failing SoD/admin tests.**
Two OIDC accounts with different issuer/subject but identical person_key cannot fill different roles. Missing/duplicate person key blocks. Admin cannot self-grant reviewer/approver/recipient; a second admin with distinct person_key must approve critical changes; admin cannot approve own change. Evidence records pseudonymous actor/approver references, never email, issuer, subject or raw claims.

- [ ] **Step 2: Verify red.**
Run pytest -q tests/test_human_identity_sod.py.
Expected: SoD and role governance fail at the missing policy seam.

- [ ] **Step 3: Implement membership and role governance.**
Add principal/membership tables with tenant-scoped unique issuer+subject and person_ref mapping. One active operator issuer per tenant. Privileged role changes use request/approve records and dual-control. First admin bootstrap is operator-only, outside public API. Update execution approval/report review to compare person_ref; retain API-key behavior only for LEGACY_API sandbox tenants.

- [ ] **Step 4: Verify green.**
Run pytest -q tests/test_human_identity_sod.py tests/test_paid_order_approval.py tests/test_paid_order_report_review.py.
Expected: HR-backed SoD passes and legacy tests remain explicitly sandbox-scoped.

- [ ] **Step 5: Integration checks.**
Run pytest -q tests/test_nina_workflow_gate.py tests/test_nina_run_approval_gate.py tests/test_postgres_integration.py.
Expected: no regression in agent evidence; migration verifier sees new identity tables.

- [ ] **Step 6: Commit.**
git add app/human_identity app/order_approval.py app/report_review.py app/main.py app/models.py app/database.py tests/test_human_identity_sod.py tests/test_paid_order_approval.py tests/test_paid_order_report_review.py
git commit -m "feat(identity): enforce HR-backed Human Gate separation"

### Task 4: Dual-signed deterministic customer bundle and offline verifier

**Files**
- Create: app/customer_bundle/manifest.py
- Create: app/customer_bundle/builder.py
- Create: app/customer_bundle/signers.py
- Create: app/customer_bundle/verifier.py
- Create: scripts/verify_customer_bundle.py
- Modify: requirements.txt, app/models.py and app/database.py
- Create: tests/test_customer_bundle.py and tests/test_customer_bundle_verifier.py

**Interfaces**
- build_order_bundle(tenant_id, order_id, profile) -> BundleArtifact
- IgorAttestor.attest(canonical_attestation: bytes) -> SignedAttestation
- OlaBundleSigner.sign(canonical_manifest: bytes) -> SignedManifest
- verify_bundle(path, trusted_keys, profile) -> VerificationReport

- [ ] **Step 1: Add failing signature/package tests.**
Test canonical manifest, stable ZIP bytes (entry order, mtime, permissions), Base64URL Ed25519 signature length 64 after decode, distinct IGOR/OLA key IDs, signature over exact canonical bytes, unknown/revoked key, file/manifest/attestation mutation, traversal, symlink, duplicate path, unexpected file, oversized archive, mismatched order/report/source/image and missing timestamp. Ensure control files are excluded from their own file list and filtered NDJSON is labelled as excerpt, not full-chain proof.

- [ ] **Step 2: Verify red.**
Run pytest -q tests/test_customer_bundle.py tests/test_customer_bundle_verifier.py.
Expected: bundle builder/signer/verifier contracts are absent and tests fail at behavior assertions.

- [ ] **Step 3: Implement minimum builder and signer interfaces.**
Pin cryptography 50.0.2. Test-only in-memory Ed25519 signers are clearly TEST_ONLY. Production rejects local/file test signer. IGOR attestation must come from a separate signer service/principal; OLA API never loads IGOR private key. Missing independent IGOR attestation returns SIGNING_BLOCKED and publishes nothing. Build filtered order evidence, canonical manifest, deterministic ZIP and offline verifier. Include approval and signing chain tips separately.

- [ ] **Step 4: Verify green.**
Run pytest -q tests/test_customer_bundle.py tests/test_customer_bundle_verifier.py.
Expected: valid test bundle verifies; all tampering and missing trust input fail closed.

- [ ] **Step 5: Integration checks.**
Run pytest -q tests/test_paid_order_report_review.py tests/test_release_source_binding.py.
Expected: bundle digest binds to reviewed report; no route claims delivery without signed verified artifact.

- [ ] **Step 6: Commit.**
git add app/customer_bundle scripts/verify_customer_bundle.py requirements.txt app/models.py app/database.py tests/test_customer_bundle.py tests/test_customer_bundle_verifier.py
git commit -m "feat(delivery): create dual-signed customer evidence bundles"

### Task 5: Recipient grants, delivery attempts, TSA and storage

**Files**
- Create: app/customer_bundle/recipients.py
- Create: app/customer_bundle/storage.py
- Create: app/customer_bundle/timestamp.py
- Modify: app/models.py, app/database.py and app/main.py
- Create: tests/test_customer_bundle_delivery.py
- Modify: tests/test_postgres_integration.py, tests/test_paid_order_report_review.py, docs/paid-order-human-gate.md and docs/postgres-runtime.md

**Interfaces**
- grant_recipient(bundle_id, recipient_ref, approver_context, reason) -> Grant
- revoke_recipient_grant(grant_id, approver_context, reason) -> dict
- record_delivery_attempt(bundle_id, recipient_ref, result) -> DeliveryAttempt
- RecipientAuthProvider.authenticate(request) -> RecipientContext; implementations for corporate OIDC and external WebAuthn are separate adapters.

- [ ] **Step 1: Add failing delivery lifecycle tests.**
Grant may exist before bundle signing. Bundle state is only PENDING/SIGNED/EXPIRED/REVOKED/INVALID. Recipient attempt state is AUTHORIZED/BLOCKED/STARTED/COMPLETED/FAILED. Each retry gets a new attempt_no. Wrong tenant/order, no grant, invalid auth, expired grant or bundle, revoked grant or invalid signature denies stream. Revoke racing stream start blocks subsequent attempts. COMPLETED is written only after stream completion; ACK is separate. Multiple recipients/re-downloads have independent attempts.

- [ ] **Step 2: Verify red.**
Run pytest -q tests/test_customer_bundle_delivery.py.
Expected: recipient grant and attempt lifecycle is absent.

- [ ] **Step 3: Implement separate grant/attempt models and storage contract.**
Allocate attempt_no under tenant write lock. Serialize revoke and stream start. Blocked attempt never mutates bundle state. Store internal object key only, not public URL. Production timestamp adapter requires RFC 3161 token or independently trusted transparency proof. Recipient auth is provider-neutral; no API-key fallback and no forced OIDC for external recipients.

- [ ] **Step 4: Verify green.**
Run pytest -q tests/test_customer_bundle_delivery.py.
Expected: multi-recipient, retry, revoke race and state-boundary assertions pass.

- [ ] **Step 5: Integration checks.**
Run pytest -q tests/test_paid_order_report_review.py tests/test_postgres_integration.py tests/test_staging_contract.py.
Expected: legacy JSON route remains sandbox-only; new delivery requires recipient identity, grant and signed bundle; PostgreSQL migration and concurrent attempts pass.

- [ ] **Step 6: Commit.**
git add app/customer_bundle app/models.py app/database.py app/main.py tests/test_customer_bundle_delivery.py tests/test_paid_order_report_review.py tests/test_postgres_integration.py docs/paid-order-human-gate.md docs/postgres-runtime.md
git commit -m "feat(delivery): add scoped recipient grants and attempts"

## Unresolved external decisions before Production GO

1. IdP and exact MFA acr/amr mapping; reliable max_age/auth_time support.
2. HR/SCIM source and trusted person_key mapping.
3. KMS/HSM supporting Ed25519 and two independent signer principals.
4. RFC 3161 TSA or immutable transparency service and trust policy.
5. Encrypted object storage, retention, deletion and crypto-shredding.
6. Recipient adapter for first pilot (recommend WebAuthn/passkey for external customers, OIDC for corporate clients).
7. Public key pinning, rotation and revocation policy.

No credentials or vendor capabilities are assumed. Mock IdP and test signers can verify CI contracts but cannot satisfy Production GO.
