# OLA signed customer evidence bundle

## Bundle format v1

The `CUSTOMER_BUNDLE_SANDBOX_V1` format is a deterministic ZIP with a signed manifest binding the immutable `bundle_id`, per-order `bundle_version`, `created_at`, and `expires_at` to the same values stored in `CustomerEvidenceBundle` and the bundle-signed Evidence event. Creation time must equal the signed_at value; expiry must be later than creation. A delivery attempt references the bundle ID/version and never changes the signed package identity. The format is a ZIP with:
- `report/report.json` — order-scoped customer report;
- `evidence/order-evidence.ndjson` — filtered order evidence excerpt;
- `igor/attestation.json` and `igor/attestation.sig` — independently signed IGOR attestation;
- optional `provenance/source-runtime.json`;
- `manifest.json` and `manifest.sig` — canonical manifest and OLA issuer signature;
- optional `timestamp/rfc3161.tsr` — timestamp proof.

The IGOR attestation and OLA manifest use distinct Ed25519 key IDs, public-key bytes and custody principals. Builder and offline verifier reject signer aliases that expose the same public key under different IDs. Signature files are Base64URL without padding and decode to exactly 64 raw bytes. `manifest.json`, `manifest.sig`, `igor/attestation.json` and `igor/attestation.sig` are excluded from the manifest's own file-hash list; the IGOR attestation digest is bound separately in the manifest.

ZIP entries use sorted paths, fixed 1980-01-01 timestamps, fixed Unix file permissions, no directory records, and no compression. This makes identical inputs and signer keys produce byte-identical ZIPs.

`evidence/order-evidence.ndjson` is an order-scoped excerpt. It preserves original record hashes for reference but is not the complete tenant chain and cannot independently recompute the tenant's whole Evidence Ledger. The verifier explicitly returns `full_tenant_chain_recomputed=false`.

## Verification and profile matrix

Offline verification rejects a missing or malformed bundle UUID, nonpositive version, creation/signing timestamp mismatch, or expiry not later than creation. Production verification also checks that source SHA is 40 hexadecimal characters, image digest is `sha256:` plus 64 hexadecimal characters, the provenance file is present and three distinct HR-backed person references are bound into the approval metadata.

The offline verifier separates cryptographic `status` from `lifecycle_status`: the same signed package may remain cryptographically `VERIFIED` or `PARTIAL`, while its lifecycle changes from `ACTIVE` to `EXPIRED` at `expires_at`. An expired signature is not described as invalid merely because time elapsed, but the API download endpoint refuses to stream an expired package.\n\nThe offline verifier requires an out-of-band trust store. The bundle binds separate approval and signing moments: `approved_at` / `approved_tip_hash` identify the state approved by the reviewer; `signed_at` / `signing_tip_hash` identify the later state rechecked immediately before signing. IGOR signs an attestation bound to the order, report digest and both Evidence tips.

| Profile | Required result | Offline outcome |
|---|---|---|
| `CUSTOMER_BUNDLE_SANDBOX_V1` | Distinct IGOR/OLA public keys and custody, valid signatures, report and file digests. `provenance_status=VERIFIED` and embedded report order binding are required for bundle status `VERIFIED`. Missing provenance or manifest-only order binding must be `PARTIAL`. | `VERIFIED` only when the signed profile says VERIFIED and all checks pass; otherwise PARTIAL or INVALID. |
| `CUSTOMER_BUNDLE_PRODUCTION_V1` | Sandbox/test keys are forbidden; HR-backed requester, approver and reviewer are three different people; exact source SHA and image digest; independently verified provenance; externally verified RFC 3161 token; embedded order binding; independent signer custody. | Any missing or invalid gate is INVALID/BLOCKED; no production VERIFIED from a missing provenance or timestamp result. |

A filtered `order-evidence.ndjson` retains original tenant-chain record hashes as references, but a recipient cannot recompute those hashes from the filtered fields. The file is therefore an OLA-signed attestation excerpt, not a complete independently recomputable tenant chain. The manifest and README explicitly keep `full_tenant_chain_recomputed=false`.

Issuance and every download both use a separately injected, out-of-band trust store; the signer objects' public metadata must match the active trust-store entries. The download path decrypts the stored ZIP, reruns the verifier, and compares bundle ID, version, profile, expiry, manifest digest and report digest to the database row before streaming any bytes. A mismatch or revoked/unknown signer blocks delivery and records a failed attempt. The client still receives the verifier and trust store independently. Example:

```json
{
  "keys": {
    "igor-prod-2026": "BASE64URL_RAW_32_BYTE_PUBLIC_KEY",
    "ola-prod-2026": "BASE64URL_RAW_32_BYTE_PUBLIC_KEY"
  },
  "revoked_key_ids": []
}
```



Run:

```bash
python scripts/verify_customer_bundle.py customer-evidence.zip --trust-store trusted-keys.json
```



Exit code `0` means cryptographically `VERIFIED` and lifecycle `ACTIVE`; `3` means cryptographically `PARTIAL`; `4` means signatures/integrity were checked but the bundle lifecycle is `EXPIRED`; `2` means `INVALID`. The CLI prints `status` and `lifecycle_status` separately. A trust store must be distributed independently from the bundle. Never trust a public key merely because it is included in the same ZIP.

## Production gate

`CUSTOMER_BUNDLE_PRODUCTION_V1` rejects local test signers and requires:
- separate remote signer custody for IGOR and OLA;
- HR-backed approver and reviewer person references;
- exact source SHA and OCI image digest;
- source/runtime provenance;
- a nonempty RFC 3161 proof accepted by an independently configured timestamp verifier;
- a separate offline timestamp trust adapter when validating the package.

The repository currently provides a remote-signing interface and trust-store contract, not a deployed KMS/HSM integration or an external timestamp authority. Therefore a production bundle cannot be emitted merely by setting environment flags. Production remains blocked until separate IGOR and OLA signer services, KMS/HSM custody, TSA trust roots, customer delivery grants, retention and revocation procedures are configured and independently tested.

## Key lifecycle and revocation

The verifier rejects unknown or revoked signer key IDs. Trust-store updates and key rotations must be distributed out-of-band. A lost or compromised key is revoked by publishing a newer trust store. Old bundle verification remains tied to the trust-store version used by the recipient; production requires a transparency timestamp so the signing time cannot be backdated by the issuer.


## Recipient grant and delivery lifecycle

The bundle lifecycle is independent from each download attempt. A signed bundle remains `SIGNED` while it is downloaded more than once or by more than one authorized recipient. Each transfer attempt is stored separately, scoped to `bundle × recipient × attempt`; a blocked recipient does not mutate the bundle lifecycle.

Recipient authentication is provider-neutral through `RecipientAuthProvider.authenticate(request) -> RecipientAuthentication(tenant_id, principal_id, auth_time, mfa_verified)`. The application re-resolves the principal, tenant membership, HR/customer person mapping and `recipient` role from its own database and requires fresh MFA; a provider cannot supply roles or person references. The working adapter today is OIDC. A WebAuthn/passkey or customer-IdP adapter can be injected at `app.state.customer_bundle_recipient_auth_provider`, but no such production adapter is shipped or configured yet.

Current recipient routes:

- `POST /checkout-orders/{order_id}/bundles` — report reviewer initiates creation; the service rechecks the approved report, full current tenant Evidence chain, exact approval Evidence and unique execution-completion Evidence, obtains IGOR/provenance attestations, builds the deterministic archive, verifies it offline, and persists it through the injected storage adapter. Returns 503 if signing, verification, timestamp or storage dependencies are absent.
- `POST /checkout-orders/{order_id}/bundle-grants` — request an order-only recipient grant (dual control required);
- `POST /checkout-orders/{order_id}/bundle-grants/{grant_id}/approve` — approve the grant by a different HR-bound human;
- `POST /checkout-orders/{order_id}/bundle-grants/{grant_id}/revoke` — revoke the grant;
- `GET /checkout-orders/{order_id}/bundles/{bundle_id}/download` — authenticated recipient download;
- `POST /checkout-orders/{order_id}/bundles/{bundle_id}/attempts/{attempt_id}/acknowledge` — explicit recipient-account acknowledgement after a completed transfer.

A transfer reaching `COMPLETED` is not automatically `ACKNOWLEDGED`. The acknowledgement requires a separate authenticated POST and appends `revenue.customer_bundle_delivery_attempt_acknowledged`. This proves that the recipient account submitted an acknowledgement; it does not prove that a person read, understood or accepted the report.

The attempt row stores `acknowledged_at` and `acknowledgement_evidence_id`. Existing SQLite databases add these columns through the runtime additive migration. PostgreSQL installations require migration `ola_customer_bundle_delivery_ack_v1`; runtime schema verification fails closed if the migration is missing.

## Current implementation boundary

The repository contains the bundle builder, dual-signature verifier, approved-report orchestration service, recipient-grant lifecycle, encrypted sandbox storage adapter and authenticated creation/download/acknowledgement routes. Creation and download use the same explicitly injected storage runtime; a local filesystem adapter is never selected on public HTTPS or a production profile. The production remote signer, independently managed trust-store distribution/rotation, external timestamp authority, durable production object-store adapter and deployment-level dependency wiring remain unconfigured. The creation route therefore fails with 503 until those dependencies are explicitly provisioned. Do not describe this as an end-to-end production customer delivery service: only the code path and fail-closed contracts exist until independent services and a real customer transfer are verified.
