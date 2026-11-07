# OLA signed customer evidence bundle

## Bundle format v1

The `CUSTOMER_BUNDLE_SANDBOX_V1` format is a deterministic ZIP with:
- `report/report.json` — order-scoped customer report;
- `evidence/order-evidence.ndjson` — filtered order evidence excerpt;
- `igor/attestation.json` and `igor/attestation.sig` — independently signed IGOR attestation;
- optional `provenance/source-runtime.json`;
- `manifest.json` and `manifest.sig` — canonical manifest and OLA issuer signature;
- optional `timestamp/rfc3161.tsr` — timestamp proof.

The IGOR attestation and OLA manifest use distinct Ed25519 key IDs and custody principals. Signature files are Base64URL without padding and decode to exactly 64 raw bytes. `manifest.json`, `manifest.sig`, `igor/attestation.json` and `igor/attestation.sig` are excluded from the manifest's own file-hash list; the IGOR attestation digest is bound separately in the manifest.

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
