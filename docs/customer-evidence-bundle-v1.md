# OLA signed customer evidence bundle

## Bundle format v1

The `CUSTOMER_BUNDLE_SANDBOX_V1` format is a deterministic ZIP with:
- `report/report.json` — order-scoped customer report;
- `evidence/order-evidence.ndjson` — filtered order evidence excerpt;
- `igor/attestation.json` and `igor/attestation.sig` — independently signed IGOR attestation;
- optional `provenance/source-runtime.json`;
- `manifest.json` and `manifest.sig` — canonical manifest and OLA issuer signature;
- optional `timestamp/rfc3161.tsr` — timestamp proof.

The IGOR attestation and OLA manifest use distinct Ed25519 key IDs, public-key bytes and custody principals. Builder and offline verifier reject signer aliases that expose the same public key under different IDs. Signature files are Base64URL without padding and decode to exactly 64 raw bytes. `manifest.json`, `manifest.sig`, `igor/attestation.json` and `igor/attestation.sig` are excluded from the manifest's own file-hash list; the IGOR attestation digest is bound separately in the manifest.

ZIP entries use sorted paths, fixed 1980-01-01 timestamps, fixed Unix file permissions, no directory records, and no compression. This makes identical inputs and signer keys produce byte-identical ZIPs.

`evidence/order-evidence.ndjson` is an order-scoped excerpt. It preserves original record hashes for reference but is not the complete tenant chain and cannot independently recompute the tenant's whole Evidence Ledger. The verifier explicitly returns `full_tenant_chain_recomputed=false`.

## Verification

The offline verifier requires an out-of-band trust store. Example:

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



Exit code `0` means `VERIFIED`; `3` means `PARTIAL`; `2` means `INVALID`. A trust store must be distributed independently from the bundle. Never trust a public key merely because it is included in the same ZIP.

## Production gate

`CUSTOMER_BUNDLE_PRODUCTION_V1` rejects local test signers and requires:
- separate remote signer custody for IGOR and OLA;
- HR-backed approver and reviewer person references;
- exact source SHA and OCI image digest;
- source/runtime provenance;
- a nonempty RFC 3161 proof accepted by an independently configured timestamp verifier;
- a separate offline timestamp trust adapter when validating the package.

The repository currently provides a remote-signing interface, not a deployed KMS/HSM integration or an external timestamp authority. Therefore a production bundle cannot be emitted merely by setting environment flags. Production remains blocked until separate IGOR and OLA signer services, KMS/HSM custody, TSA trust roots, customer delivery grants, retention and revocation procedures are configured and independently tested.

## Key lifecycle and revocation

The verifier rejects unknown or revoked signer key IDs. Trust-store updates and key rotations must be distributed out-of-band. A lost or compromised key is revoked by publishing a newer trust store. Old bundle verification remains tied to the trust-store version used by the recipient; production requires a transparency timestamp so the signing time cannot be backdated by the issuer.


## Recipient grant and delivery lifecycle

The bundle lifecycle is independent from each download attempt. A signed bundle remains `SIGNED` while it is downloaded more than once or by more than one authorized recipient. Each transfer attempt is stored separately, scoped to `bundle × recipient × attempt`; a blocked recipient does not mutate the bundle lifecycle.

Current recipient routes:

- `POST /checkout-orders/{order_id}/bundle-grants` — request an order-only recipient grant (dual control required);
- `POST /checkout-orders/{order_id}/bundle-grants/{grant_id}/approve` — approve the grant by a different HR-bound human;
- `POST /checkout-orders/{order_id}/bundle-grants/{grant_id}/revoke` — revoke the grant;
- `GET /checkout-orders/{order_id}/bundles/{bundle_id}/download` — authenticated recipient download;
- `POST /checkout-orders/{order_id}/bundles/{bundle_id}/attempts/{attempt_id}/acknowledge` — explicit recipient-account acknowledgement after a completed transfer.

A transfer reaching `COMPLETED` is not automatically `ACKNOWLEDGED`. The acknowledgement requires a separate authenticated POST and appends `revenue.customer_bundle_delivery_attempt_acknowledged`. This proves that the recipient account submitted an acknowledgement; it does not prove that a person read, understood or accepted the report.

The attempt row stores `acknowledged_at` and `acknowledgement_evidence_id`. Existing SQLite databases add these columns through the runtime additive migration. PostgreSQL installations require migration `ola_customer_bundle_delivery_ack_v1`; runtime schema verification fails closed if the migration is missing.

## Current implementation boundary

The repository contains the bundle builder, dual-signature verifier, recipient-grant lifecycle, encrypted sandbox storage adapter and authenticated download/acknowledgement routes. The production remote signer, external timestamp authority, durable production object-store adapter and deployment-level dependency wiring remain unconfigured. Do not describe the feature as an end-to-end customer delivery service until a bundle-creation orchestration route is wired to an independently verified IGOR attestation, approved provenance, production signers, timestamp authority and durable object storage.
