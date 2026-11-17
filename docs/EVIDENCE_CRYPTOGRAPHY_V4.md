# Evidence Cryptography V4 — implementation contract

## State
This branch introduces isolated V4 cryptographic primitives and contract tests.
It does not yet migrate production writers, change the default verifier, or enable
production writes. V4 remains opt-in until the complete acceptance gate passes.

## Key custody
Inject `OLA_EVIDENCE_V4_KEYRING_JSON` as a JSON object mapping key IDs to
base64-encoded random key material, and `OLA_EVIDENCE_V4_ACTIVE_KEY_ID`.
Each key must contain at least 32 random bytes. The keyring belongs in an
external secret manager; it must never be persisted in the evidence database,
logs, repository, or backups containing evidence rows.

## Authenticated envelope
HMAC-SHA256 authenticates domain, protocol version, key_id, tenant_id, sequence,
predecessor hash, record type, producer, and canonical payload JSON. The
record hash is lowercase hexadecimal. Verification selects exactly the
record's key_id; missing or unknown keys fail closed.

## Compatibility
V1/V2/V3 verification must remain on the historical verifier paths. This
module's mixed-chain entry point requires an explicit V3 verifier callback and
does not reinterpret legacy records. Production integration must supply an
independently maintained V3 verifier and real immutable V1/V2/V3 fixtures.

## Required release gates
- All write paths produce V4.
- All read paths verify mixed V3/V4 chains.
- Rotation, key loss, unknown key_id, key substitution, restart,
  backup/restore, and mixed-chain scenarios pass.
- IGOR uses an independently implemented verifier.
- CI separates functional cryptographic tests from secret-management tests.
- Independent security review has no open critical findings.

Until then: `PRODUCTION_BLOCKED`.
