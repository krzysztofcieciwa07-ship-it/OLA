# OLA di-OS — P0 remediation audit trail

**Snapshot:** 2026-11-21  
**Branch / scope:** documentation and test preparation only. This file records observed state, responsible owner, the next safe action and the proof required for closure. It is not a production approval.

## Status vocabulary

- `BLOCKED`: a required control is known to be absent or failing.
- `UNKNOWN`: source or target cannot be established from available evidence.
- `PARTIAL`: code or isolated test proof exists, but the target/runtime/approval proof is missing.
- `WAITING_OWNER`: the next action requires an authorized operator, account owner or external reviewer.
- `VERIFIED`: exact source and intended environment independently satisfy the acceptance criteria. Do not set this based on source, mock, CI on another SHA or stale screenshots.

## P0 / P1 remediation register

| ID | Priority | Workstream / source | Observed state | Next safe remediation | Owner | Closure evidence |
|---|---:|---|---|---|---|---|
| OLA-GOV-001 | P0 | Main ruleset / Issue #150 | GitHub main API reports `protected=false`; required status-check enforcement is off. Active ruleset #25853037 only has deletion + non-fast-forward and empty branch scope. | Authorized owner/admin applies and verifies exact `refs/heads/main` protections; independent reviewer validates negative cases. | Krzysztof / repo admin | Exported effective rule details, exact branch match, required check names, independent approval, signature policy, negative test missing review/check = BLOCK. |
| OLA-REL-001 | P0 | Production host / Issue #158 and #153 | Railway production `Ola di-os` contains n8n, Postgres and evolution-api; no OLA FastAPI API/worker. FastAPI lives in a distinct staging project. | Decide the exact production project/environment/services and data plane. Collect hosting/IAM/network/TLS evidence before any change. | Krzysztof / hosting operator | Service IDs, source/image digest, active domain, external `/readyz`, network allowlist, TLS chain, monitoring and rollback proof for one exact SHA. |
| OLA-DB-001 | P0 | Railway ↔ Neon binding | `OLA_DATABASE_URL` exists on staging API and worker, but values are redacted. The referenced Neon project/branch cannot be independently mapped. | Use an approved read-only identity to report database/project/branch and current user; compare with deployment/environment metadata. Never expose DSN. | DB owner | Sanitized project/branch IDs, effective runtime role, schema migration head, RLS/grants and identity of the workload used for the query. |
| OLA-WRITER-001 | P0 | Evidence writer inventory / PR #269–#272 | Several repository audits exist. PR #270 → #271 → #272 are stacked; documents explicitly state that source inventory/export verification is not deployed DB attestation. | Preserve stack order; collect read-only DB roles/ACLs/triggers/functions and independently sampled DB↔log exports for the selected real DB. | DB owner + security reviewer | Complete writer/principal map, no unexplained writer, sanitized exports and reproducible offline correlation verifier + SHA-256 manifests. |
| OLA-SC-001 | P1 | Gitleaks / run #44900512969 | Supply Chain Evidence Gate failed on main SHA `8adf30cd...`; Gitleaks artifact #14705294063 has 23 findings. | Triage every finding individually against current source/history. Do not call a leak or false positive without evidence; no broad allowlist. | Security owner | 23 row-by-row dispositions, path/line/commit, secret class and exposure assessment; revocation/rotation proof for confirmed live credentials. |
| OLA-CFR-001 | P1 | OIDC verifier / PR #276 | Draft foundation returns verified (issuer, subject, tenant claim) but is not connected to trusted membership or role resolution. | Independent review of exact head and schema; continue only as a separate CFR-2P-02 integration. | OLA + external reviewer | Signature/claim tests, then a separately reviewed membership/role contract and negative tests. |
| OLA-CFR-002 | P0 | Signed Approval Record / this branch | Pure schema and local contract primitives are prepared; not wired, no signer, no membership DB and no nonce persistence. | Review `docs/security/CFR-2P-02_SIGNED_APPROVAL_CONTRACT_V1.md`; correct design before schema/migration implementation. | Security reviewer + Krzysztof | Independent approval of canonical bytes, role authority, one-use nonce, signer custody, exact effect and Human Gate flow. |
| OLA-HUMAN-001 | P0 | Human-in-loop and separation of duties / Issue #172, #158 | Main paid-order/report flows use technical API-key IDs/roles. Human Gate in recent Ollama artifact is explicitly PENDING; CI does not approve. | Keep the gate fail-closed. Define a real reviewer identity, step-up authentication, operator display, expiry, revocation and audit evidence. | Human operator + identity owner | Real authorized person performs explicit action; immutable identity binding, exact order/report digest, nonce, timestamp and independent verifier receipt. |
| OLA-EVIDENCE-001 | P1 | Evidence V4 / IGOR / PR #250, #267, #275, Issue #172 | Evidence V4 and verifier code exist; migration/runtime target proof and policy closure are separate. | Reconcile exact-source migration/IGOR contracts using a disposable restored DB; do not duplicate writers. | OLA + DB reviewer | Exact SHA, independent full-chain verification, tenant/type/identity binding, replay/tamper negatives, migration restore and SLI evidence. |
| OLA-LLM-001 | P1 | Real LLM / Issue #20 | Real Ollama is proven in PR #276 exact-SHA CI; OpenAI runtime is not proven. The six agent invocations ran `in_process`; verifier does not prove process isolation or semantic correctness of capabilities. | Preserve the Ollama artifact proof. Add Ollama runtime version capture and pin installer/runtime; keep OpenAI a separate credential-gated lane. | Runtime owner | Provider/version/model digest, exact source/image/run ID, response IDs, independent verifier, and separate process-isolation tests if claimed. |
| OLA-REV-001 | P1 | Revenue / Issue #24 | Synthetic Stripe webhook tests exist; no independently verified live customer transaction established. | Only after core auth/DB/E2E gates close, request separate approval for a small, reversible live transaction. | Business/payment owner | Stripe LIVE session/event, verified signature, payment/order/run/evidence IDs, customer delivery and refund/settlement linkage. |
| OLA-NOVA-001 | P1 | NOVA / Issue #162 | Canonical backend, identity provider and live multi-user runtime not identified. | Identify exact source repository, deployment and test identities first. No mock chat as evidence. | Integration owner | Two independent accounts, tenant boundary negatives, ACK/reconnect/replay tests and operation_id evidence. |
| OLA-CODEX-001 | P1 | Codex Bridge / Issue #161 | Canonical bridge source/service not identified; OLA #160 + Vantage #13 are prerequisites only. | Identify canonical package/service digest and staging boundary; do not substitute generic Codex integrations. | Integration owner | Signed per-action operation_id, tenant/repo/action scope, sandbox and independently verified result signature. |

## Known environment boundaries

### Railway production project — `Ola di-os`

- Project ID: `d85ed597-09aa-45dd-935f-a2d3a9410e2d`; environment ID: `92baf1d5-e9ed-493c-92bb-06baa2e880e9`.
- n8n: image `n8nio/n8n:latest`, volume 500 MB at `/data`, one replica.
- Postgres: image `ghcr.io/railwayapp-templates/postgres-ssl:18`, volume 500 MB at `/var/lib/postgresql/data`, one replica.
- evolution-api: image `evoapicloud/evolution-api:latest`, volume 500 MB at `/evolution/instances`, one replica.
- No OLA FastAPI API or paid-order worker is present in this environment. Tags `latest` are not immutable image identities.

### Railway FastAPI staging project

- Project ID: `06e1fb77-5c6c-45f4-86a3-70423b09c648`; environment ID `49e9669f-ac25-41a1-a366-1fc458c73484`.
- API `ola-fastapi-api`: service ID `23f2097d-d99a-46e2-9b5a-7ff57c803fb7`; deployment `7d166aec-5c5c-45f2-ad41-a6b5a5993f65`; source branch `test/staging-panel-overlay-20261120-2052Z`, SHA `151fe8684e7eaefffb6d29b611593d200f6ee8ca`; `/readyz` healthcheck; public Railway service domain exists; one replica, no volume.
- Worker `ola-paid-order-worker`: service ID `8dfa21a9-c35c-4b9e-ad24-338fe8470216`; deployment `4ef6b5a1-930d-466e-bcd7-3344e03d5f55`; main SHA `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`; one replica, no volume.
- Both services were online with 1/1 replica and no recent failure/warning at the latest read. Their different SHAs and absent persistent volumes mean this is not a same-release, durable production system.

## Evidence handling rules

Every new row must capture:
- stable workstream ID and acceptance statement;
- source system, UTC time and exact SHA/run/deployment/resource identifier;
- environment name and resource identity (never secret values);
- capture method/command/query and scope/limitations;
- raw artifact URI and SHA-256;
- redaction statement and independent verifier outcome;
- next owner and required human gate.

Do not attach secret values, complete database URLs, tokens, customer card data or raw personal identities to issues or artifacts.

## Stop conditions

Do not deploy, run production migrations, alter Railway config, rotate production credentials, create approvals, authorize paid execution, or bypass branch review under this work package. Each is a separate owner-authorized action. Passing tests only proves the tested contract at the exact candidate SHA.
