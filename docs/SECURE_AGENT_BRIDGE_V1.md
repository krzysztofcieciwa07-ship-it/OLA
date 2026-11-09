# Secure Agent Bridge v1

## Boundary and behavior

The FastAPI runtime exposes `POST /api/v1/secure-bridge/invoke`. Version 1 allows exactly one operation: `agent.run`, scoped by `agent:run`, for a registered OLA agent identity. The endpoint invokes the existing `run_agent_task` path through `ExecutionSafetyGate`; it does not return a payload hash and mislabel that as execution.

No private signing key is stored by OLA. Each trusted agent signs requests with its own Ed25519 private key. OLA receives only the corresponding 32-byte public key.

## Runtime configuration

Set these deployment variables in the runtime secret/configuration manager. Do not commit live values.

- `OLA_SECURE_BRIDGE_AUDIENCE`: exact receiver audience string, for example `ola-secure-agent-runtime`.
- `OLA_SECURE_BRIDGE_CLOCK_SKEW_SECONDS`: integer from 1 to 300; recommended 60.
- `OLA_SECURE_BRIDGE_KEYS_JSON`: JSON array of trusted keys. Each entry contains `key_id`, `tenant_id`, `agent_id`, `public_key_b64` (standard Base64 encoding of the 32 raw public-key bytes), and `scopes` (for this version: `[\"agent:run\"]`).
- `OLA_SECURE_BRIDGE_REVOKED_KEY_IDS`: optional comma-separated key IDs to revoke.

Example with placeholders only:

```json
[
  {
    "key_id": "agent-worker-01",
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "agent_id": "agent-001",
    "public_key_b64": "BASE64_OF_32_BYTE_ED25519_PUBLIC_KEY",
    "scopes": ["agent:run"]
  }
]
```

For rotation, configure the new key ID and public key alongside the old one, move the client to the new private key, verify traffic, then add the old key ID to the revocation list. The client must keep its private key in a secret manager or HSM; it must never be sent to OLA.

## Signed request

Required headers:

- `X-Key-Id`
- `X-Timestamp`: canonical 10-digit Unix seconds
- `X-Nonce`: 32 cryptographically random bytes, lower-case hex (64 characters)
- `X-Signature-Ed25519`: 64-byte signature as 128 hexadecimal characters
- `Content-Type: application/json`

The exact UTF-8 signing message is the following newline-separated sequence, with no trailing newline:

```text
OLA-SECURE-BRIDGE-V1
<key_id>
<timestamp>
<nonce>
POST
/api/v1/secure-bridge/invoke
<audience>
<SHA256(raw HTTP body) as lower-case hex>
```

Example body:

```json
{"action":"agent.run","payload":{"task":"verify the service"}}
```

The signature binds HTTP method, exact route, audience and raw request bytes. JSON is parsed only after signature verification; duplicate JSON object keys are rejected.

## Replay, authorization and evidence

The verified nonce is atomically stored as a one-way digest under a unique `(key_id, nonce_hash)` constraint. Expired rows are pruned in the same transaction. The operation fails closed if persistent nonce storage is unavailable. A replay returns HTTP 409.

Signature failures do not mutate agent state. A supplied key ID is not proof of the caller's identity, so automatically quarantining an ID after forged signatures would let any unauthenticated caller deny service to a legitimate agent. Revocation is explicit through trusted deployment configuration. Any future automatic quarantine must be driven only by authenticated policy events and have a controlled recovery path.

The evidence chain receives an authenticated-request record before execution and a result record afterward. If execution may have occurred but the result evidence write fails, the endpoint returns `EXECUTION_RESULT_UNRECORDED` and instructs the caller to reconcile rather than retry blindly.

Replay protection applies to the exact nonce. This v1 endpoint does not promise exactly-once semantics if a client deliberately submits the same task again with a *new* nonce. Clients must use a stable higher-level job ID and reconcile uncertain outcomes before resubmitting. A durable business idempotency ledger is a separate follow-up.

## PostgreSQL deployment

The migration role must run `python scripts/migrate_postgres.py` after this schema change. The API runtime verifies the nonce table, its unique constraint and the `ola_secure_bridge_nonce_v1` migration marker; it never performs PostgreSQL DDL at startup.

## Explicit v1 limits

- Only `agent.run` is enabled; arbitrary MCP/tool names are not accepted.
- No automatic quarantine is triggered by unauthenticated failures.
- Trusted and revoked keys are supplied by deployment configuration.
- The endpoint does not authorize HIGH-risk actions or replace Human Gate approval.
- This change does not add endpoint-specific rate limiting; enforce a conservative limit at the API gateway/edge before enabling public traffic.
- No production rollout is implied by this code or its tests.
