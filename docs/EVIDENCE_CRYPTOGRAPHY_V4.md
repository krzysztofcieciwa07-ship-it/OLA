# Evidence Cryptography V4 — implementation contract

## State

V4 core now has a storage envelope compatible with the existing immutable
`EvidenceRecord` columns. This is still an opt-in branch change: no production
writer is migrated, no default verifier is changed, and no production secret is
provisioned. Release remains blocked.

## Storage contract — no schema migration

The current `EvidenceRecord` schema is retained:

- `tenant_id`
- `seq`
- `record_type`
- `payload_json`
- `prev_hash`
- `record_hash`

V4 metadata is stored inside `payload_json` under the reserved top-level key
`__ola_evidence_v4__`. Its exact schema is:

```json
{
  "__ola_evidence_v4__": {
    "version": 4,
    "key_id": "key-2026-01",
    "record_type": "provenance.runtime",
    "producer": "ola_runtime"
  }
}
```

Application payload fields remain at the top level. V4 writers must reject both
reserved keys `__ola_evidence_v2__` and `__ola_evidence_v4__` in caller payloads.
The V2 metadata key and its historical contents are never rewritten.

The V4 authenticated material includes the domain, version, key_id, tenant_id,
sequence, predecessor hash, record type, producer, and the exact canonical
`payload_json`. The record hash is lowercase HMAC-SHA256 hex. No database
columns or existing V1/V2/V3 bytes need to be rewritten.

## Key custody

Inject `OLA_EVIDENCE_V4_KEYRING_JSON` as a JSON object mapping key IDs to
base64-encoded random key material, and `OLA_EVIDENCE_V4_ACTIVE_KEY_ID`.
Each key must contain at least 32 random bytes. The keyring belongs in an
external secret manager; it must never be persisted in the evidence database,
logs, repository, or evidence backups. Evidence backups and secret backups are
separate recovery artifacts.

Verification selects exactly the `key_id` embedded in the V4 metadata. Missing
or unknown keys fail closed. Rotation changes the active key for new writes but
retains old keys for historical reads. The in-memory keyring is defensively
copied and immutable.

## Legacy compatibility

- V1: no `__ola_evidence_v2__` metadata; historical unkeyed V1 digest.
- V2: `__ola_evidence_v2__.version = 2`; historical domain-separated SHA-256.
- V3: `__ola_evidence_v2__.version = 3`; historical HMAC derivation from
  `OLA_API_KEY_PEPPER` using `OLA-EVIDENCE-CHAIN-KEY-V3`.
- V4: `__ola_evidence_v4__.version = 4`; independent keyring and HMAC domain.

The V3 algorithm is recoverable from immutable source commit
`c46b469836fc841638654850158c82d728164f3c`, file
`app/hashchain.py` (blob
`60f12f96bcb0291201b432747cfd16b12921d2c3`). A V3 compatibility test and
historical-format fixture must retain that source provenance. V3 key custody
must remain distinct from V4 custody; do not substitute or rotate the old
pepper as part of V4.

The mixed-chain adapter checks global sequence/predecessor continuity and
verifies V4 itself. Legacy V1/V2/V3 segments are passed intact to an explicit
legacy verifier. It must never silently treat a legacy record as V4 or fall
back to a V4 key for legacy verification.

## Required release gates

- All five evidence writers produce V4 using the storage contract above.
- All read paths verify mixed V1/V2/V3/V4 chains.
- Immutable, provenance-labelled V1/V2/V3 fixtures pass exact historical
  verification; fixture provenance is not inferred from a synthetic example.
- Rotation, key loss, unknown key_id, key substitution, restart,
  backup/restore, and mixed-chain scenarios pass.
- IGOR uses an independently implemented verifier and does not import the
  writer's hash implementation.
- CI separates functional cryptographic tests from secret-management tests.
- Independent security review has no open critical findings.

Until every gate is evidenced at the exact release SHA: `PRODUCTION_BLOCKED`.
