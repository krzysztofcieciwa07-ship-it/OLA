# OLA di-OS — dependency, runtime and supply-chain inventory

**Snapshot:** 2026-11-21  
**Scope:** canonical main `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`, PR #276 runtime evidence `6bcc5fd66e21479c84ba62e17d02398f48d80d9c`, Railway read-only service metadata and Supply Chain run #44900512969. No secrets or raw finding values included.

## 1. Python application requirements on main

Source: `requirements.txt` (blob SHA `16ff790582b7a0fdbf633a2d618b50bc76a397a2`).

| Package | Pin |
|---|---:|
| fastapi | 0.142.2 |
| sqlalchemy | 2.1.1 |
| httpx | 0.28.1 |
| pytest | 9.0.3 |
| uvicorn | 0.54.0 |
| msgpack | 1.2.3 |
| setuptools | 84.1.0 |
| urllib3 | 2.8.0 |
| wheel | 0.48.0 |
| psycopg[binary] | 3.3.8 |

Candidate branch additions:
- PR #276 `PyJWT[crypto]==2.15.1`: runtime verifier dependency; not yet on main, needs exact-head CI and review.
- CFR-2P-02 `requirements-contracts.txt`: `jsonschema==4.26.0`, test-only. New Python package CI explicitly installs this file for pytest; Dockerfile still installs only `requirements.txt`, so the JSON Schema validator is not added to the production image.

## 2. Container and OS baseline

Main `Dockerfile` (blob SHA `733b1f5cc654f5c277b8ae0383f54e965f236696`):
- Base image: `debian:13-slim` tag, not digest pinned.
- OS build performs `apt-get update` + `apt-get upgrade`; package versions are not locked to an immutable snapshot.
- Python 3.13 and Python venv are installed from the Debian repositories.
- Image labels `org.opencontainers.image.revision` from build arg `OLA_SOURCE_COMMIT`.
- App copied to `/app` and made read-only; runtime runs as UID 10001; persistent path declared as `/data/ola.db`.
- Pytest removed from production venv; pip/setuptools/wheel tooling removed after dependency installation.

Local staging Compose uses a named `ola-staging-data` volume and binds HTTP only to `127.0.0.1:18080`; it is not public staging proof.

**Hardening backlog:** pin base image by digest; pin Python/OS package snapshot or produce a reproducible SBOM; record build provenance and package hashes; scan source and final image; prove the deployed image digest matches source SHA; verify vulnerability policy and rebuild cadence.

## 3. GitHub Actions and installer trust

- The primary Python workflow pins checkout action by commit SHA; the workflow tests the current source on Python 3.12.
- The Ollama workflows install Ollama by running `curl -fsSL https://ollama.com/install.sh | sh`. This is a floating remote installer script, not a verified pinned installer digest.
- The OLA image is tagged from exact Git source SHA and checked against `org.opencontainers.image.revision`.
- Workflow artifact records model metadata, model digest and runtime image ID. It does not capture the installed Ollama CLI version.

**Required before production provenance:** pin the Ollama installer or verify an independently published release checksum/signature; record `ollama --version`, binary digest, model manifest and content digest; fail if any expected digest changes; include these identities in the signed provenance statement.

## 4. Ollama real-runtime proof available for PR #276

Exact source: `6bcc5fd66e21479c84ba62e17d02398f48d80d9c`.

| Item | Captured value |
|---|---|
| Workflow | Real LLM Ollama Runtime Gate, run #44896190323 |
| Job | `ollama-real-runtime`, job #136822246963 |
| Model tag | `qwen2.5:0.5b-instruct` |
| Model digest | `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67` |
| Model file size | 397,821,319 bytes |
| Format / quantization | GGUF / Q4_K_M |
| Ollama model artifact | #14703757477; archive SHA-256 `b574c56b7ca384f4a001b059598212b98a58e5bbfea1a5da7803dc3bd4e5cf30` |
| Runtime image ID | `sha256:76aa5f1d05516e59110c1884d5b51fcfd23475995f196a388ac006d71bcc926b` |
| Image revision label | exact PR SHA `6bcc5fd...` |
| Runtime proof | 6 model calls, provider `ollama`, final result `391`, run_id `c49b5bb9-2c4e-4e16-8dc3-0160ac7dcc4a` |
| Flow artifact | #14704306681; SHA-256 `cf75758f1b50d819fcf6251f0d51a278c54a373cff43e8f39bb23af4f793cbda` |
| IGOR artifact | #14703991812; SHA-256 `7369ba8d69119a3de78cfbf431c6454a13db4a54ee35eba64919265c13171b69` |
| IGOR result | chain VERIFIED, replay VERIFIED, tamper BLOCK, Human Gate PENDING |
| Execution boundary | `in_process`; separate verifier process, but no proof that six agent roles run as isolated OS processes |

The model tag is mutable; the recorded digest is the identity for this run. This proves only the model artifact in this exact PR CI run, not main or production. The installed Ollama CLI version is **NOT RECORDED** and remains an explicit provenance gap.

The IGOR bundle's Human Gate file says: `PENDING — Human approval is not performed by CI automation.` This is the expected state. Do not reinterpret a CI artifact or model call as a person approving the action.

## 5. Production/staging image references observed in Railway

| Project/service | Image/source reference | Finding |
|---|---|---|
| Railway production / n8n | `n8nio/n8n:latest` | Floating tag, 500 MB volume, no OLA FastAPI. |
| Railway production / Postgres | `ghcr.io/railwayapp-templates/postgres-ssl:18` | Mutable tag, 500 MB volume; actual OLA DB binding not proven. |
| Railway production / evolution-api | `evoapicloud/evolution-api:latest` | Floating tag, 500 MB volume; no proof it is an OLA subsystem. |
| FastAPI staging / API | Git `test/staging-panel-overlay-20261120-2052Z`, SHA `151fe8684e7eaefffb6d29b611593d200f6ee8ca` | One replica, no attached volume. |
| FastAPI staging / worker | Git `main`, SHA `8adf30cd5e41a18a5345f66e67f5ddcdbc164862` | One replica, no attached volume. |

Staging API and worker are on different SHAs. Railway returns environment variable names but redacts `OLA_DATABASE_URL` values; the Neon project/branch remains UNKNOWN. No attempt was made to reveal the DSN.

## 6. Gitleaks finding register — all 23 remain UNCLASSIFIED

Source: Supply Chain Evidence Gate run #44900512969, main SHA `8adf30cd...`; artifact #14705294063; SARIF ZIP SHA-256 `4576d241c5b45810abd52b528ec39cebb6626060d5e9f4a5872c14664a4928a8`.

No matched string or secret value is reproduced here. Duplicate SARIF findings remain separate evidence rows until deduplication is established by the scanner fingerprint and exact source.

| # | Rule | Path | Line | First known commit context |
|---:|---|---|---:|---|
| 1 | generic-api-key | `tests/test_gitleaks_exact_scan.py` | 15 | `30e6099d...` |
| 2 | generic-api-key | `tests/test_agent_supervisor.py` | 384 | `7191d9d8...` |
| 3 | generic-api-key | `tests/test_agent_supervisor.py` | 388 | `7191d9d8...` |
| 4 | generic-api-key | `tests/test_evidence_concurrency.py` | 142 | `69a4d272...` |
| 5 | stripe-access-token | `tests/netlify-nina-pilot.test.mjs` | 121 | `ea796edf...` |
| 6 | generic-api-key | `tests/test_human_identity_sod.py` | 99 | `64f7a0ff...` |
| 7 | generic-api-key | `app/customer_bundle/signers.py` | 37 | `2ebdd228...` |
| 8 | generic-api-key | `app/customer_bundle/signers.py` | 37 | `87775f5e...` |
| 9 | generic-api-key | `tests/test_human_identity_sod.py` | 91 | `b12abf9e...` |
| 10 | generic-api-key | `tests/test_checkout_idempotency.py` | 381 | `5966fe03...` |
| 11 | generic-api-key | `tests/test_staging_safety.py` | 11 | `210a5207...` |
| 12 | generic-api-key | `tests/test_staging_safety.py` | 34 | `210a5207...` |
| 13 | generic-api-key | `tests/test_staging_safety.py` | 11 | `65432cc1...` |
| 14 | generic-api-key | `tests/test_staging_safety.py` | 34 | `65432cc1...` |
| 15 | generic-api-key | `tests/test_staging_safety.py` | 11 | `a3c181cb...` |
| 16 | generic-api-key | `tests/test_staging_safety.py` | 34 | `a3c181cb...` |
| 17 | generic-api-key | `tests/test_staging_safety.py` | 11 | `5af50ef2...` |
| 18 | generic-api-key | `tests/test_staging_safety.py` | 34 | `5af50ef2...` |
| 19 | generic-api-key | `tests/test_staging_safety.py` | 11 | `7b825b3b...` |
| 20 | generic-api-key | `tests/test_staging_safety.py` | 34 | `7b825b3b...` |
| 21 | generic-api-key | `tests/test_staging_safety.py` | 11 | `95d001f8...` |
| 22 | generic-api-key | `tests/test_staging_safety.py` | 34 | `95d001f8...` |
| 23 | generic-api-key | `tests/test_api_key_v2.py` | 43 | `60378da7...` |

Disposition for all rows: **UNCLASSIFIED**. Rule + file path are not enough to decide whether a detector match is test-only, synthetic, revoked, historical or live. The next audit must inspect the exact blob at each commit and current main/history without printing the matched value, trace its origin and exposure, and only then classify. Confirmed credential exposure requires owner-controlled revocation/rotation and evidence; false-positive status requires a narrow, reproducible explanation. No broad allowlist.

## 7. Evidence sources and next proof

- Main requirements: `requirements.txt`.
- Production image build: `Dockerfile`.
- Local staging boundary: `deploy/staging/compose.yaml`.
- Ollama runtime workflows: `.github/workflows/ollama-real-runtime.yml`, `.github/workflows/nina-igor-ollama.yml`, `.github/workflows/igor-independent-ollama-evidence.yml`.
- Supply-chain workflow: `.github/workflows/supply-chain-evidence.yml`.

Next required evidence:
1. Exact, pinned dependency lock or hash-locked install for application and build tools.
2. Immutable base image digest and OS package snapshot, SBOM bound to image digest.
3. Pinned/verifiable Ollama installer and exact CLI version output.
4. Model manifest digest and any relevant layer/quantization metadata preserved with each run.
5. Complete Gitleaks per-finding adjudication and confirmation whether any credential is currently active.
6. Runtime deployment image digest and source SHA for API and worker on the same intended environment.
