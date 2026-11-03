# OLA — local-only Docker staging and evidence rehearsal

This is a real container execution test, **not a public production deployment**. It is intentionally bound to `127.0.0.1:18080`. Synthetic records are written to a disposable persistent Docker volume and independently verified after restart.

## Requirements

Docker Engine with Compose v2, Python 3.12+, Git, local checkout, and permission to run Docker. Run from the repository root:

```bash
export OLA_RUNTIME_COMMIT="$(git rev-parse HEAD)"
export OLA_API_KEY_PEPPER="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python scripts/staging_rehearsal.py
unset OLA_API_KEY_PEPPER
```

Never commit or share the pepper. The rehearsal creates unique Docker Compose project names, cleans **its own** volume, and writes only a sanitized `staging-proof.json` with commit, verified chain root, synthetic tenant ID, checks and duration.

## Gates

- Source SHA equality before build; Docker Compose config validation.
- HTTP `GET /readyz` returns `core_status=READY`, while `system_acceptance=NOT_VERIFIED`.
- No or incorrect API key returns HTTP 401.
- Synthetic `POST /audit` produces 5 V2 evidence records.
- Independent SHA-256 V2 verification recomputes hashes without producer functions.
- SQLite append-only trigger rejects a direct mutation.
- Container restart preserves the evidence chain root.
- Readiness stays green for an uninterrupted 12-second observation window.

## Explicitly out of scope

No public DNS, TLS, operator approval for production, remote durable backup/restore, high availability, infrastructure-as-code for a real VPS, multi-service end-to-end NOVA/Codex/Vantage, independent human review, or commercial-user workload is proven here.

**Deployment decision:** `LOCAL_REHEARSAL` may pass. `PRODUCTION_10_OF_10` remains `BLOCKED` until separate external evidence and approval. A GitHub CI success is never treated as proof that public production is operating.
