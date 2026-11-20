# P0 Writer-Path Classification — bounded repository search (2026-11-20)

## Scope and epistemic limit
This is a bounded source-search classification against the repository default-branch snapshot (search results referenced commit `8adf30cd5e41a18a5345f66e67f5ddcdbc164862`). It is not an exhaustive filesystem/AST scan, not a deployed workload inventory, and not proof of production reachability. Search-result snippets and selected files were inspected; classifications below must be reconciled against full repository and infrastructure inventories.

## Candidate path classification

| Path / artifact | Classification | DB target / likely context | Production reachability | Evidence required to close |
|---|---|---|---|---|
| `app/database.py` `append_evidence_atomic` | Canonical application writer wrapper | Configured runtime DB | Application runtime candidate | Runtime deployed source SHA, DB identity and event telemetry |
| `app/evidence_writer.py` `append_evidence_v4_locked` | Low-level append primitive; caller lock contract | Configured runtime DB | Application runtime candidate | Call-site enumeration + lock/transaction tests |
| `app/nina_workflow_gate.py` | Direct locked approval writer | Runtime DB | App runtime | Contention/failure tests + telemetry |
| `app/order_approval.py` | Direct locked approval writer | Runtime DB | App runtime | Contention/failure tests + telemetry |
| `app/report_review.py` | Direct locked review/delivery writer | Runtime DB | App runtime | Contention/failure tests + telemetry |
| `app/paid_order_execution.py` | Direct lifecycle writer | Runtime DB | App runtime/worker candidate | Worker deployment inventory + telemetry + tests |
| `.github/workflows/nina-igor-ollama.yml` | CI workflow; raw SQL seeds tenant/API-key fixture; evidence DB is tenant-filtered export from disposable container | CI-local SQLite at `/data/ola.db` | Workflow candidate; source explicitly uses test key/material and local Ollama | Workflow run/artifact review, runner egress/secret scopes; confirm never uses production DB URL |
| `tests/test_staging_verify.py` | Test fixture inserts rows directly | Test SQLite | Test-only by source intent | Confirm no production credential/target in execution environment |
| `scripts/staging_verify.py`, `scripts/staging_rehearsal.py` | Verification / rehearsal; reads evidence, test mutations may occur | Staging/disposable DB by context | Not established | Invocation inventory, target DB and credential scope |
| `scripts/verify_readme_claims.py` | Test/claim verifier; direct mutation attempt | Test DB by context | Not established | Invocation inventory and DB target |
| `scripts/verify_business_invoice.py`, `scripts/verify_agent_runtime.py` | Read-only verifier scripts based on snippets | SQLite supplied by operator | Not writer paths in observed snippets | Full code review, invocation and credential scope |
| `workstation/OLA-Workstation.ps1` | Workstation disposable Docker setup; direct seed of tenants/API key; deliberate tamper probe against disposable container | Local Docker `/data/ola.db` | Production reachability UNKNOWN | Secret inventory, host/network isolation and explicit prod-access tests |
| `app/database.py` schema migration routines / `scripts/migrate_postgres.py` | Schema/trigger/migration writer | PostgreSQL schema | Privileged migration path candidate | Runner/role/approval/backup/rollback/ownership/network evidence |
| Cloud/DB console, bastion, owner/superuser, alternate SQL clients | Not discoverable by repository search | Production infrastructure | UNKNOWN | IAM, role memberships, audit logs, network controls and identity inventory |
| Schedulers, external integrations, unlisted workers | Not proven absent | UNKNOWN | UNKNOWN | Deployed inventory, secret scopes, DB connection telemetry |

## Source signals observed
- Runtime documentation specifies a separate runtime role with SELECT/INSERT on evidence_records and no UPDATE/DELETE/TRUNCATE, and separate migration credential.
- Application startup/schema verification checks append-only triggers and privilege signals, but source checks are not live effective privilege evidence.
- Search results include operational scripts and CI workflows; direct SQL hits must not be treated as production writer without target and identity classification.
- The Ollama workflow uses a CI-only test key, a local disposable container and SQLite; it seeds tenant/API key with raw SQL, then exports tenant-scoped evidence from the container. This does not prove isolation of all CI workflows or account-level controls.
- Workstation script snippets include a disposable Docker database and an intentional append-only mutation probe. This does not prove the workstation cannot reach production.

## Open evidence required
1. Enumerate all deployed DB-capable identities and roles, including inherited memberships, ownership, grants, schema privileges, TRUNCATE, trigger disable/drop, and escalation paths.
2. Reconcile all workloads, workers, schedulers, migration jobs, CI runners, consoles, bastions and workstation processes against the identities above.
3. Establish exact production DB target, effective session/user identity, TLS and source network per workload.
4. Obtain production DB and telemetry exports from independently controlled sources, freeze population and scope, reconcile all IDs, then compare fields/timestamps. Authenticate exports and their completeness independently.
5. Resolve every unknown/unclassified path. Unknown is not absence.

## Status
Writer universe: **IN PROGRESS / NOT EXHAUSTIVE**.
Production GO: **NOT AUTHORIZED**.
