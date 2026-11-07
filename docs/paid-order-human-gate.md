# Paid order Human Gate and execution dispatch — sandbox contract

## Scope and boundary

This flow applies only to Stripe **test-mode** checkout. It includes an order-bound Human Gate, a durable outbox, and a single-attempt worker that runs the existing NINA → IGOR path with a fixed `safe_expression` capability. SQLite remains the local default; PostgreSQL support for the evidence chain, Human Gate, and outbox uses transaction-scoped advisory locks and row locks. This code path still requires a successful real-PostgreSQL CI run before production use. It does **not** enable Stripe LIVE, production execution, public customer data intake, report delivery, or Ed25519/external attestation.

## State progression

- Checkout/payment: `CREATING → CHECKOUT_CREATED → PAYMENT_PROCESSING → PAID_PENDING_REVIEW`
- Human Gate: `PAID_PENDING_REVIEW → APPROVED_FOR_EXECUTION`
- Execution outbox: `QUEUED → RUNNING → EXECUTED_REVIEW_REQUIRED | EXECUTED_BLOCKED | FAILED | INTERRUPTED | BLOCKED`

Approval writes the hash-chained `human.revenue_execution_approval` record, updates the order-control row, and creates exactly one `checkout_execution_jobs` outbox row **in the same database transaction**. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL takes a tenant advisory transaction lock and locks the order/control rows. The outbox stores the exact task and the approval-record hash. The job is unique per order.

A trusted worker claims a queued job using SQLite `BEGIN IMMEDIATE` or a PostgreSQL `SELECT FOR UPDATE` job-row lock followed by the tenant advisory lock. It verifies the complete tenant evidence chain and exact Human Gate record, confirms the current build source matches the approval source, and writes `revenue.execution_started` before invoking NINA. The paid-order worker is constrained to `safe_expression`; it does not accept customer-selected tools. Provenance and decision-candidate evidence records carry the order and execution-job IDs.

The existing NINA execution pipeline produces a decision report, and IGOR independently verifies the runtime evidence. `EXECUTED_REVIEW_REQUIRED` is only assigned when NINA, IGOR, provenance, and replay all return `VERIFIED`. Other outcomes are `EXECUTED_BLOCKED` or `FAILED`. The current paid-order worker intentionally requests only `safe_expression`; in the verified local test run the invocation type is `local_deterministic_model` and `real_llm_invoked` is false. Therefore this is proof of the controlled NINA/IGOR runtime path, **not** proof of an external/real LLM call. Even a successful execution returns `customer_delivery: NOT_DELIVERED`; the report still requires a separate release/review/delivery path.

## At-most-once and recovery

The worker has a single attempt per outbox job. It never automatically replays a job after `FAILED`, `INTERRUPTED`, `BLOCKED`, or a lost claim. A `RUNNING` job older than 900 seconds is marked `INTERRUPTED` with a trusted evidence record. This is intentionally **at-most-once**, not an exactly-once guarantee for an external LLM provider: a crash after provider execution but before durable completion is ambiguous and requires manual reconciliation. No second NINA run is started automatically.

This is safer than blind retries but does not yet provide automated recovery of an ambiguous execution. A future retry must be a separately reviewed, new authorization bound to a new execution attempt and an independently confirmed absence of completed side effects.

## Worker operation

The local staging Compose file starts `ola-paid-order-worker` alongside the API. The SQLite profile mounts the same disposable volume. For PostgreSQL, set `OLA_DATABASE_URL` for the API and worker, run `scripts/migrate_postgres.py` first with the separate `OLA_DATABASE_MIGRATION_URL`, and grant the runtime role only the required DML privileges. The worker polls every five seconds and marks jobs older than 900 seconds as interrupted rather than replaying them. See `docs/postgres-runtime.md` for role and migration details.

To run one batch manually inside the application environment:

```bash
python scripts/run_paid_order_worker.py --once
```

To run continuously:

```bash
python scripts/run_paid_order_worker.py --poll-seconds 5 --stale-after-seconds 900
```

The internal HTTP adapter `POST /internal/checkout-execution/{job_id}/run` additionally requires `X-OLA-Worker-Token`. It is disabled unless `OLA_EXECUTION_WORKER_TOKEN` is configured with at least 32 characters. The bundled staging worker calls the service locally from the worker container and does not expose this secret through the API.

## Verification boundary

SQLite uses `BEGIN IMMEDIATE`; PostgreSQL uses transaction-scoped tenant advisory locks and row-level locks. Real PostgreSQL behavior is covered by `tests/test_postgres_integration.py` and `.github/workflows/paid-order-postgres.yml`; this environment did not have a PostgreSQL server, so that integration test was not run locally. Evidence is SHA-256 hash-chained by the OLA runtime, not an external signature. API-key separation is not SSO/MFA. Public TLS/DNS, production source/image attestation, offsite backup/restore, SLO/latency/load behaviour, customer data retention, final report release and secure delivery, Stripe LIVE, and production deployment are still unverified and remain blocked.


## Public payment redirect privacy boundary

`GET /payment-success` is a public Stripe return URL. It returns only coarse payment/execution/delivery status and the next gate. It MUST NOT return the submitted task, report body, run identifier, evidence identifiers or hashes, approval identifiers, or execution-job identifiers. Possession of a Stripe Checkout Session ID is not authorization to read OLA customer evidence.

An authenticated tenant operator obtains the current evidence-chain tip from `GET /evidence/tip` using `X-API-Key`. This endpoint returns only `{tip_hash, record_count}`. Detailed evidence retrieval continues to require tenant authentication.

This status redirect is not a customer report-delivery mechanism. Reports remain internal and `customer_delivery=NOT_DELIVERED` until a separately authenticated reviewer and a protected delivery channel are implemented and verified.
