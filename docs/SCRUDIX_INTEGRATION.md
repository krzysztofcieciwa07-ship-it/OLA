# Scrudix → OLA Evidence: user-export import (v0)

Status: **RECORDED / source UNVERIFIED**. This integration imports a Scrudix
Usage Reports Export already downloaded by the operator. It does **not** fetch
from Scrudix automatically: there is no verified report API contract in this
repository. The `imx_` Scrudix token is **not used** by this adapter.

The adapter reuses `POST /evidence` and `GET /evidence/{id}` with OLA's tenant
API key. It does not create another evidence store, alter the hash-chain schema,
or execute an agent. No third-party report content or personal email address
is written into append-only evidence: only its SHA-256, byte count, filename,
claimed generation time, import time, and provenance labels are recorded.

## Usage

From the repository root with the project dependencies installed:

```bash
python -m scripts.import_scrudix_report /path/to/scrudix-usage.md --dry-run

export OLA_BASE_URL="https://your-ola-api.example"
export OLA_API_KEY="<existing OLA tenant API key>"
python -m scripts.import_scrudix_report /path/to/scrudix-usage.md
```

Windows PowerShell (replace the placeholder with your configured OLA URL):

```powershell
$env:OLA_BASE_URL = "https://your-ola-api.example"
$env:OLA_API_KEY = "<existing OLA tenant API key>"
python -m scripts.import_scrudix_report "D:\Scrudix-usage-report.md" --dry-run
python -m scripts.import_scrudix_report "D:\Scrudix-usage-report.md"
```

Do not commit credentials or paste live keys into shell history. Prefer an
approved secret manager or process environment. The URL must use HTTPS,
except for local loopback during development. Requests have a 15-second timeout.

The adapter:

1. Rejects unexpected format, empty/non-UTF-8 or larger-than-2-MiB exports.
2. Hashes the original bytes; never sends the raw report to OLA.
3. Writes a tenant-scoped `external.scrudix.report` evidence record.
4. Reads that record back and independently recomputes its record hash using
   `app.hashchain.compute_record_hash`.
5. Prints `RECORDED`, `record_integrity: PASS`, and
   `source_authenticity: UNVERIFIED` on success.

`record_integrity: PASS` verifies the individual record's content/hash
consistency, **not** Scrudix's authorship or the entire tenant hash-chain.
The raw export must be retained separately if later source verification is
required. Reimporting the same file appends another record; the SHA-256 can be
used to identify duplicate exports during review.

## Boundary before live API synchronization

Do not guess undocumented Scrudix report endpoints or send a user token to a
discovered URL. Live synchronization requires an official endpoint, auth scope,
response schema, pagination/rate limits, and source provenance contract.
Only then add a read-only fetch step and map its payload to this same evidence
record type. IGOR must continue to treat unsigned external content as
`UNVERIFIED` until independent source attestation is available.
