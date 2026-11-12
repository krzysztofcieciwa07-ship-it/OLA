# OLA — Evidence-Driven Execution Runtime

OLA is a Python/FastAPI application for controlled agent execution, tenant-scoped evidence capture, hash-chain integrity checks, replay-oriented verification, and a payment-triggered execution path.

This repository is the canonical OLA runtime source. A successful test or CI workflow proves only the checks that actually ran; it does not, by itself, establish production readiness or a live customer transaction.

## Features

- **Controlled agent execution** — registered agents run through explicit execution and risk controls.
- **NINA orchestration** — bounded task planning and execution through registered capabilities.
- **IGOR verification** — independent checks over runtime results and evidence records.
- **Tenant isolation** — API-key-based tenant identity and tenant-scoped evidence access.
- **Evidence integrity** — append-only SQLite records with per-tenant sequence numbers and a SHA-256 hash chain.
- **Replay and decision reports** — reconstruction and verification of recorded execution events.
- **Human Gate** — second-identity review paths bound to the evidence-chain tip; approval is not deployment authorization.
- **Business workflows** — controlled invoice processing and Stripe Checkout/webhook handling.
- **Operational verification** — Docker health checks, automated tests, and GitHub Actions security, runtime, and provenance gates.

## Technology stack

- **Language:** Python 3.11+ (the Docker image currently uses Python 3.13).
- **API:** FastAPI, served by Uvicorn.
- **Persistence:** SQLAlchemy with SQLite for the current application database.
- **Runtime packaging:** Docker on Debian 13 slim, running as an unprivileged user.
- **Testing:** pytest and HTTPX.
- **Payments:** Stripe Checkout and signed webhook integration.
- **CI/CD and assurance:** GitHub Actions, CodeQL, runtime tests, and provenance/evidence workflows.

The repository does not currently declare PostgreSQL, Supabase, NumPy, or OpenTelemetry as runtime dependencies. Do not infer those technologies from the broader product roadmap.

## Repository scope

The current source tree contains:

- `app/` — FastAPI application, tenant/API-key handling, agent runtime, NINA orchestration, IGOR verification, execution safety gate, Human Gate decision model, evidence persistence, replay, and Stripe checkout/webhook integration.
- `evidence_graph.py` — a separate SQLite-backed Evidence Graph projection module. The package metadata currently describes this module; it is not a complete description of the whole FastAPI application.
- `tests/` — unit and integration tests for runtime, evidence, agent controls, replay, payment handling, and related contracts.
- `scripts/` — runtime, provenance, stress, continuity, and evidence verification helpers.
- `docs/` — implementation notes, design records, and operational documentation.
- `web/` — static application entry page.
- `workstation/` — workstation-related assets.
- `.github/workflows/` — CI, security, runtime, provenance, and production-evidence workflows.
- `revenue/` — revenue-related assets and supporting material.

## Runtime and persistence facts

- Python requirement in `pyproject.toml`: Python 3.11 or newer.
- The Docker image installs Python 3.13 and starts `uvicorn app.main:app` on port 8000.
- SQLite remains the default local database. Its default file is `ola.db`; the path can be overridden with `OLA_EG_DB_PATH`.
- PostgreSQL can be selected with `OLA_DATABASE_URL` (preferred) or `DATABASE_URL`. PostgreSQL URLs are normalized to SQLAlchemy's `postgresql+psycopg` dialect; Psycopg 3 is pinned in `requirements.txt`.
- Evidence writes use SQLite `BEGIN IMMEDIATE` or PostgreSQL transaction-scoped, tenant-keyed advisory locks. Both preserve per-tenant sequence numbers and previous-record hashes.
- PostgreSQL schema DDL is an explicit migration step (`scripts/migrate_postgres.py`) using `OLA_DATABASE_MIGRATION_URL`. API and worker startup verify the migrated schema and append-only triggers but do not create PostgreSQL tables with runtime credentials.
- PostgreSQL support has a dedicated real-server integration test and GitHub Actions workflow. It is not production-certified until that workflow has passed on the exact candidate SHA and operational backup, TLS, privileges, pooling, and failover checks are verified.
- `pyproject.toml` metadata names the distribution `ola-evidence-graph` and declares FastAPI; `requirements.txt` supplies the pinned runtime/test dependencies used by the Docker build.

## Main application surfaces

The inspected application source defines these HTTP routes:

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Serves the static web entry page. |
| GET | `/health` | Basic process health response used by the container health check. |
| POST | `/chat` | Tenant-authenticated chat surface. |
| POST | `/checkout` | Creates a Stripe Checkout Session when configured. |
| GET | `/payment-success` | Retrieves and checks a Checkout Session and its matching webhook execution. |
| POST | `/stripe/webhook` | Verifies the Stripe signature and processes the checkout event. |
| POST | `/evidence` | Appends tenant-submitted evidence, while rejecting reserved internal evidence types. |
| GET | `/evidence/{record_id}` | Reads one evidence record within the authenticated tenant boundary. |
| POST | `/audit` | Runs the currently supported controlled fault-and-recovery audit scenario. |
| POST | `/agent-run` | Requests a registered agent execution through the execution safety controls. |
| POST | `/nina-run` | Runs the bounded NINA orchestration path and returns IGOR, provenance, replay, policy, and Human Gate results. |
| POST | `/nina-run/{run_id}/approve` | Records a second-identity approval bound to the current evidence-chain tip. |
| POST | `/nina-workflow` | Starts the opt-in bounded parallel workflow path; disabled unless explicitly enabled by configuration. |
| GET | `/nina-workflow/{run_id}/report` | Refreshes a read-only, tenant-scoped IGOR report bound to the runtime commit and evidence tip. |
| POST | `/nina-workflow/{run_id}/approve` | Records explicit second-identity workflow review; does not authorize deployment or PR merge. |
| POST | `/business-invoice-run` | Runs the controlled invoice-processing workflow for tenant-submitted invoice JSON. |

Check `app/main.py` for the complete route contract and current request/response details.

## Trust and control boundaries

- Unknown, malformed, or unverifiable states must not be promoted to `VERIFIED` or `ALLOW`.
- NINA is a bounded orchestration layer over registered capabilities; it does not create verification evidence.
- IGOR is an independent verification component in the application flow; its presence in code is not proof that every execution is independently verified in production.
- The current `ExecutionSafetyGate` denies unknown actions and returns `REVIEW` for HIGH-risk actions. Its source explicitly says a caller-controlled boolean is not trusted Human Gate approval and that a trusted approval verifier is not yet integrated at that execution boundary.
- The current `HumanGate` model checks the review actor, approval decision, and candidate status. Do not treat this small decision model alone as proof of a complete authenticated production approval workflow.
- A local hash chain supports integrity checking; it does not independently prove the truth of submitted observations or the identity of an external source.
- Stripe integration code is present. A configured checkout path or passing mocked test is not proof of a live paid order, successful fulfillment, or production revenue. Those require exact live Stripe event/session evidence and a verified execution result.

## Local setup

Requirements: Python 3.11+ and a working shell.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the application:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check basic health:

```bash
curl --fail http://127.0.0.1:8000/health
```

Run the test suite:

```bash
pytest
```

Build and run the container:

```bash
docker build -t ola:local .
docker run --rm -p 8000:8000 -v ola-data:/data ola:local
```

The Dockerfile sets `OLA_EG_DB_PATH=/data/ola.db` and runs as an unprivileged `ola` user. Configure Stripe environment variables only in a local secret store or deployment secret manager; never commit credentials.

## Stripe configuration

The current checkout integration is sandbox-only. Configure these values through a local secret store or deployment secret manager:

- `STRIPE_SECRET_KEY` — a Stripe test-mode secret key (`sk_test_` or `rk_test_`); live keys are rejected.
- `STRIPE_WEBHOOK_SECRET` — the signing secret for the sandbox webhook endpoint.
- `OLA_STRIPE_PRICE_ID` — the exact Stripe Price ID accepted for the OLA offer. The webhook retrieves the authoritative Checkout Session with expanded line items and verifies this Price ID, EUR currency, quantity 1, and `amount_total == unit_amount`. The source no longer hardcodes a EUR 99.00 amount.
- `OLA_PUBLIC_BASE_URL` — the server-owned public origin used for Stripe success and cancel redirects. HTTPS is required except for localhost development.

`POST /checkout` requires both tenant authentication (`X-API-Key`) and an `Idempotency-Key` header containing 8–128 characters from `A-Z a-z 0-9 . _ : -`. The same key and same task must be reused when retrying a request. Reusing the key with a different task returns HTTP 409. A new logical checkout requires a new key.

Example (replace the environment variables with values from your local secret store):

```bash
curl --fail-with-body -X POST "$OLA_BASE_URL/checkout" \
  -H "X-API-Key: $OLA_API_KEY" \
  -H "Idempotency-Key: $CHECKOUT_REQUEST_ID" \
  -H "Content-Type: application/json" \
  -d '{"task":"Review the evidence trail for this workflow"}'
```

The application creates an additive `checkout_orders` table through SQLAlchemy metadata initialization. It persists the tenant-scoped order reservation before calling Stripe, binds the Stripe session to that order, and passes a stable provider idempotency key derived from the order ID. Evidence appends for the same checkout are deduplicated under the tenant-scoped database write lock (SQLite `BEGIN IMMEDIATE` or PostgreSQL advisory lock).

An order left in `CREATING` can be retried with the same client key while the Stripe idempotency retention window is safe. After 23 hours, automatic retries fail closed with HTTP 409 and require manual Stripe reconciliation; do not generate a new key to bypass that block.

The signed webhook accepts only sandbox events. It retrieves the session from Stripe rather than trusting the event's embedded payment fields, checks the session's `order_id`, tenant, and exact stored Checkout Session binding, and moves the order through `PAYMENT_PROCESSING` to `PAID_PENDING_REVIEW`. Evidence writes are idempotent and can be retried after an interrupted webhook. A confirmed payment does **not** authorize NINA execution; Human Review remains a separate gate.

No live Stripe payment or production checkout is implied by these code paths or their mocked tests. Product pricing and commercial approval remain separate decisions.

## Verification and release status

Use the GitHub Actions workflows and the scripts in `scripts/` as evidence sources, but inspect each run against the exact commit SHA being evaluated. A workflow file existing in the repository is not evidence that it passed.

Before any production claim, independently verify at minimum:

1. the exact source commit and its required check runs;
2. test and security results for that exact SHA;
3. container build and runtime health;
4. evidence-chain integrity and replay/tamper checks;
5. provenance and release artifact attestations;
6. real Stripe checkout, signed webhook, confirmed payment, execution, and customer deliverable evidence;
7. the required human approval and production authorization.

Until all required evidence is present, describe production readiness as `UNKNOWN`, `PARTIAL`, or `BLOCKED` as appropriate — never infer `VERIFIED` from documentation or workflow definitions.

## Security

Read [SECURITY.md](SECURITY.md) before reporting vulnerabilities or preparing a release. Never commit API keys, Stripe secrets, signing keys, customer data, or production evidence containing sensitive information.


## Repository governance

Engineering rules, contribution steps, and the pull-request evidence format are maintained in docs/ENGINEERING_STANDARD.md, CONTRIBUTING.md, and .github/PULL_REQUEST_TEMPLATE.md. Security reporting and release-evidence requirements are defined in SECURITY.md. Dependency update checks are configured through Dependabot.

Portfolio ownership and fork provenance: [Repository Catalog](docs/REPOSITORY_CATALOG.md), [machine-readable catalog](docs/REPOSITORY_CATALOG.json), [fork recovery map](docs/FORK_RECOVERY_MAP.md), and [metadata plan](docs/REPOSITORY_METADATA_PLAN.md). These are inventory records, not release-readiness claims.
