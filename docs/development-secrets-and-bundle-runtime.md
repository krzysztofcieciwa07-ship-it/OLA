# Development secrets and customer-bundle runtime

## Required secret entries

The Development environment uses two different encryption keys. Store both in the platform secret manager, not in source control, a tracked `.env` file, or logs.

| Secret | Purpose | Required encoding |
|---|---|---|
| `OLA_HUMAN_SESSION_ENCRYPTION_KEY` | Fernet encryption for server-side Human Identity sessions | Fernet-compatible URL-safe Base64 containing 32 random bytes |
| `OLA_CUSTOMER_BUNDLE_STORAGE_KEY` | AES-256-GCM encryption for local customer-bundle storage | Base64 containing 32 random bytes |

The two decoded keys must be different. Do not reuse one key for both purposes.

Run the presence-only check from the project root:

```bash
python scripts/check_development_secrets.py
```

The command prints only the variable names and `PRESENT` / `MISSING`. It never prints or hashes values. Exit code 0 means both entries are present; exit code 1 means the environment is still blocked. This command does not validate a real sign-in, decrypt a prior session, or prove customer delivery.

## Local loopback Development runtime

The API automatically creates the test-only customer-bundle runtime only when all of these are true:

- `OLA_DEPLOYMENT_PROFILE=development`;
- `OLA_PUBLIC_BASE_URL` is either an HTTP loopback origin such as `http://127.0.0.1:8000`, or exactly `https://${REPLIT_DEV_DOMAIN}` inside the Replit project editor;
- for the Replit path, `REPLIT_DEV_DOMAIN` must be present, match the origin hostname exactly, and `REPLIT_DEPLOYMENT` must be unset;
- both encryption secrets are present, valid, distinct 32-byte keys.

Replit documents `REPLIT_DEV_DOMAIN` as available in the project editor and unavailable in Deployments. OLA requires an exact hostname match and still rejects a published deployment marker.

The local signer seeds are derived from the Human Identity key with HKDF-SHA256 and separate purpose labels. This makes the test-only signatures stable across local API restarts. It does **not** create independent IGOR and OLA custody; the signers remain test-only and the production bundle builder rejects them for the production profile.

The bundle storage key is used only for AES-256-GCM local storage. The default storage directory is `/tmp/ola-development-customer-bundles`; override it with the non-secret `OLA_CUSTOMER_BUNDLE_STORAGE_PATH` setting when needed.

The Development IGOR attestation provider is explicitly labelled `DEVELOPMENT_FIXTURE`. No independent production provenance or RFC 3161 timestamp provider is configured. Therefore bundles produced by this runtime remain `PARTIAL`, and must never be described as independently verified production evidence or customer-ready production delivery.

## Public HTTPS and production boundary

An arbitrary HTTPS origin is classified as production by the Human Identity deployment-profile guard, even when an environment label says Development. The only HTTPS exception is the exact Replit workspace hostname injected as `REPLIT_DEV_DOMAIN`, while running in the editor and with no `REPLIT_DEPLOYMENT` marker. A `*.replit.app` published app, a custom domain, a mismatched `*.replit.dev` host, or a Replit Deployment never receives the Development signers. This is intentional: test-only keys and fixture attestations must not become a fallback for published services.

Production customer-bundle issuance still requires separately operated OLA and IGOR signing services, an independently managed trust store, independently verified source/image provenance, a trusted timestamp authority, and approved encrypted object storage. Presence of the two Development encryption secrets does not satisfy those controls and does not enable Stripe LIVE or production delivery.
