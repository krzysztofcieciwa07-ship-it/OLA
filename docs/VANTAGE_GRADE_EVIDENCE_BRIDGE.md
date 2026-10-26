# Vantage v0.3 -> OLA Evidence v2 bridge

Status: **STAGING / operator-triggered**, **NOT production-approved**.
This module reuses existing OLA `POST /evidence` and `GET /evidence/{record_id}`.
It does not call `/agent-run`, change Safety Gate, bypass Human Gate, or
create another database. Source repository:
[krzys167-crypto/Vantage-v0.3](https://github.com/krzys167-crypto/Vantage-v0.3),
verified against grader `result`/`signature` Ed25519 canonical JSON protocol at
`8a0c5296fd9968b85290549d74e1a1f0d3ed9d5c`.

## Inputs and trust boundary

1. Export the **real grader result JSON** from your trusted Vantage instance,
   e.g. `GET /v1/attempts/<attempt_id>/result` with authorized access.
   Never send your grader's private key to OLA.
2. Obtain the grader's **public** key PEM through an independently authenticated
   operator channel (the Vantage grader exposes `GET /v1/pubkey`).
3. PIN its SHA-256 *PEM file bytes* from a separately trusted channel. Do not
   treat a key provided inside the receipt as trusted.
4. Configure a pre-existing tenant API key and matching expected OLA tenant ID
   using the operator's secret management process.

### Windows PowerShell (repo checked out on D:)

```powershell
Set-Location D:\OLA
$env:VANTAGE_GRADER_PUBKEY_SHA256 = (Get-FileHash D:\OLA\grader-public.pem -Algorithm SHA256).Hash.ToLower()
$env:OLA_BASE_URL = 'https://your-existing-ola-api.example'
$env:OLA_TENANT_ID = '<known-tenant-id>'
# OLA_API_KEY must already be provided by your approved secret manager.
python -m scripts.import_vantage_grade D:\OLA\vantage-grade.json --pubkey D:\OLA\grader-public.pem --dry-run
python -m scripts.import_vantage_grade D:\OLA\vantage-grade.json --pubkey D:\OLA\grader-public.pem
```

### Linux

```bash
export VANTAGE_GRADER_PUBKEY_SHA256="$(sha256sum grader-public.pem | cut -d' ' -f1)"
export OLA_BASE_URL="https://your-existing-ola-api.example"
export OLA_TENANT_ID="<known-tenant-id>"
# Supply OLA_API_KEY via a secret manager, not source files or shell history.
python -m scripts.import_vantage_grade vantage-grade.json --pubkey grader-public.pem --dry-run
python -m scripts.import_vantage_grade vantage-grade.json --pubkey grader-public.pem
```

The operator must independently confirm that the pinned public-key hash belongs
to the intended Vantage grader. A self-reported identity does not establish
trust. Missing trust pin, malformed signed report, mismatched signature,
malformed tenant configuration, unsafe URL, redirects, non-v2 evidence or
read-back hash mismatch **fail closed**.

## Result and limits

- The adapter verifies the signature **locally** with OpenSSL Ed25519 over
  Vantage's exact `json.dumps(result, sort_keys=True, separators=(',', ':'))`
  bytes. This is the same canonicalization used by the external grader.
- `external.vantage.grade` is a tenant-API event. OLA writes only: SHA-256 of
  the raw report, signed result, signature, public key, scenario name; signature
  check marker, a claimed attestation boolean, and source provenance labels.
  **No user ID, email, attempt ID, full report, API key or private key** is stored.
- The adapter reads the record back and checks the exact tenant ID, ID, type,
  Evidence v2 `__ola_evidence_v2__` producer binding, sequence and record hash.
- This does **not** independently verify the entire tenant chain, Vantage's
  measurement truth, its grader deployment identity, remote host status or
  source timestamp. The importer is an operator-controlled client; OLA does
  not itself re-check the Ed25519 signature at ingest. Its result is **RECORDED**,
  never an internal trusted IGOR verdict or production authorization.
- The original signed receipt must be retained separately for audit.
  Reimporting the same signed receipt creates another append-only record:
  deduplication must be decided at the server before commercial fulfillment.
- Production promotion needs: independently managed persistent grader key,
  independently deployed witness, server-side cryptographic attestation of the
  payload, replay/tamper rejection, signed source commit, all exact-SHA CI,
  independent review and Human Gate approval.

## Existing ecosystem boundaries

- Existing PR #83 provides a **Vantage advisory detector**. It does not grant
  execution authority and is not replaced by this signed-grader receipt bridge.
- Existing PR #121 handles **Scrudix user-export** content and is separate.
- The OLA runtime remains the only executor. Vantage v0.3 remains a separate
  incident-range product. Nothing here implies a live Vantage or Replit deploy.
