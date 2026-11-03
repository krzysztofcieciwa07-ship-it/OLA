# OLA di-OS: isolated staging rehearsal

This is **not** a public deployment and **not** certification of full OLA di-OS. The service binds **127.0.0.1** and mounts a named SQLite volume so evidence survives process restart. The run deliberately uses a throwaway local identity, not live operator keys.

Run from repo root with Docker Compose v2, Python 3.13 and a running Docker daemon:

```bash
python scripts/staging_rehearsal.py
```

Set `OLA_STAGING_COMMIT` to a specific 40-hex commit to use a concrete source revision, or rely on the runner's `GITHUB_SHA`/local git HEAD. The script derives a new random `OLA_STAGING_PEPPER` for its own process and does not print it. It creates a uniquely named Compose project, checks `/health` and `/readyz`, writes an actual **synthetic** V2 evidence record, stops/starts the container, reads and verifies the same hash chain and ensures SQLite rejects an UPDATE. The ephemeral Compose volume is deleted in cleanup after the successful test.

Checks deliberately do not claim that OLA has production MFA, backup/restore to an independent medium, TLS, a verified image signature, NOVA E2EE, or an external Vantage run. Container health and local volume persistence are insufficient for production readiness.

Workflow: `.github/workflows/ola-staging-rehearsal.yml`. Artifacts: `staging-evidence.json` (no credentials). A failed step keeps the release gate **BLOCKED**, even if `/health` returned 200.

To deploy on actual VPS, use a separate approved runbook, image digest and verified provenance, encrypted backup+restore drill, access policy, HTTPS, and independent review.
