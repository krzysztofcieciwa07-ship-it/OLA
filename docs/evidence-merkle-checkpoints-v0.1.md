# OLA Evidence Merkle Checkpoints v0.1

## Purpose and boundary

This is an additional integrity layer over the existing append-only Evidence Chain.
It does not replace `app.hashchain.verify_chain`, alter the evidence table, or
create execution authority. A checkpoint is created only after the complete chain
for one tenant has been read in sequence order and verified from `GENESIS_HASH`.

Version 0.1 intentionally requires a complete chain beginning at sequence 0.
Segment checkpoints, external checkpoint chaining, persistence, API routes, and
automatic scheduling are deferred until a separately reviewed v0.2 design.

## Data flow

1. The server derives `tenant_id` from authenticated context. Never take it
   directly from an untrusted request body or header.
2. `load_tenant_evidence_records` reads rows filtered by that tenant and ordered
   by `seq` in one database read.
3. `create_checkpoint` validates required fields, enforces a single tenant and
   contiguous sequence starting at zero, then runs the existing
   `app.hashchain.verify_chain`. Any chain error fails closed.
4. Each Merkle leaf hashes canonical JSON containing `tenant_id`, `seq`,
   `record_type`, and the already-verified `record_hash`.
5. A manifest binds the tenant, full sequence range, genesis predecessor,
   record count, chain tip, Merkle algorithm/root, timestamp, and signer identity.
6. Ed25519 signs the canonical manifest. The envelope includes the public key
   so a recipient can verify the signature, but self-publication does not make
   that key trusted.
7. `build_inclusion_proof` creates an individual membership path. A verifier
   checks the manifest signature, tenant/range binding, proof depth, sibling
   direction implied by the leaf index, and the final Merkle root.

## Merkle construction

- Hash function: SHA-256.
- Leaf: `SHA256(0x00 || canonical_json(leaf_record))`.
- Internal node: `SHA256(0x01 || left_32_bytes || right_32_bytes)`.
- Odd-width level: duplicate the last node as its own right sibling.
- Leaf index is zero-based and must equal the evidence sequence number in v0.1.
- Proof depth must equal the exact number of tree reductions implied by
  `record_count`. For an unpaired last node, the proof sibling must equal the
  current node; arbitrary siblings are rejected.

The distinct 0x00/0x01 prefixes prevent a leaf encoding from being confused
with an internal-node encoding.

## Public API

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.evidence_merkle import (
    create_checkpoint,
    load_tenant_evidence_records,
    build_inclusion_proof,
    verify_checkpoint_signature,
    verify_inclusion_proof,
)

# Example only: production signing keys belong in a KMS/HSM or approved secret store.
private_key = Ed25519PrivateKey.generate()
# Keep the same read snapshot for checkpoint creation and proof generation.
records = load_tenant_evidence_records(authorized_tenant_id)
checkpoint = create_checkpoint(
    records,
    signing_key=private_key,
    signer_key_id="ola-evidence-checkpoint-2026-01",
)
proof = build_inclusion_proof(records, leaf_index=3, checkpoint=checkpoint)

signature_status = verify_checkpoint_signature(
    checkpoint,
    trusted_signer_sha256=PINNED_PUBLIC_KEY_SHA256,
)
membership_ok = verify_inclusion_proof(
    checkpoint,
    proof,
    trusted_signer_sha256=PINNED_PUBLIC_KEY_SHA256,
    require_trusted_signer=True,
)
```

The example generates an ephemeral key for clarity only. Production must inject
a persistent key from an approved signer, with key ID and public-key SHA-256
pinned independently by the verifier. The helper does not authenticate callers.

## Signed envelope

`manifest` is the only signed payload. `manifest_sha256` is SHA-256 over its
canonical JSON bytes. The signature envelope carries Ed25519 signature bytes,
the raw 32-byte public key (base64), key ID, and public-key fingerprint.
The verifier checks all fields agree before verifying the signature.

Two separate facts are reported:

- `signature_valid`: the signature verifies against the public key carried in
  the envelope.
- `signer_trusted`: the public-key fingerprint equals a separately configured
  trusted fingerprint.

A valid self-signed envelope with no independently pinned fingerprint is
integrity-verifiable but **not authenticated as OLA or as a customer organization**.

## Privacy and operational notes

- A leaf contains hashes and tenant/sequence/type bindings, not the evidence
  payload. The signed manifest does not disclose raw payload JSON.
- SHA-256 commitments can still reveal equality or enable guessing attacks for
  low-entropy payloads if payload hashes are exposed elsewhere. Do not treat a
  Merkle root as encryption or anonymization.
- The module is read-only: no migration, database mutation, evidence append, API
  endpoint, or production deployment is introduced.
- The full-chain algorithm is O(n) memory and O(n) hashing. Large-tenant
  pagination/streaming and periodic checkpoint snapshots require a new design
  that cryptographically chains trusted prior checkpoints; they are not silently
  approximated in v0.1.
- Do not label this a zero-knowledge proof. It is a conventional Merkle
  inclusion proof.

## Verification

Run:

```bash
python -m pip install -r requirements.txt
python -m compileall -q app tests
pytest -q tests/test_evidence_merkle.py
pytest -q -ra
```

Negative coverage includes modified payloads, out-of-order records, mixed
tenants, cross-tenant proof replay, changed leaf data, missing siblings,
invalid odd-leaf paths, manifest tampering, empty chains, and explicit signer
trust pinning.
