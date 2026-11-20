# P0 Allowed Writer Universe — repository enumeration (2026-11-20)

## Scope and method
Enumerated the Git tree for `main` (repository tree SHA observed during this review) across `app/`, `scripts/`, `.github/workflows/`, `deploy/`, and `workstation/`; then performed targeted source searches for SQL mutations, ORM EvidenceRecord construction/addition, database connection primitives, and evidence table names. This is a repository snapshot inventory, not proof of deployed infrastructure or exhaustive dynamic-code discovery.

## Allowed paths (proposed allowlist)
| ID | Path / class | Environment/target | Classification | Evidence / remaining condition |
|---|---|---|---|---|
| AP-01 | API entrypoints in `app/main.py` via central atomic writer | Runtime | ALLOW candidate | Source path structurally reviewed; deployed entrypoint/identity/telemetry not attested |
| AP-02 | `app/nina_execution.py` NINA shared execution service | Runtime | ALLOW candidate | Calls `append_evidence_atomic`; runtime source review |
| AP-03 | `app/nina_workflow_gate.py`, `app/order_approval.py`, `app/report_review.py` | Runtime | ALLOW candidate | Source-reviewed direct paths use transaction/lock/validation; deployed trace remains pending |
| AP-04 | `app/paid_order_execution.py` and `scripts/run_paid_order_worker.py` | Runtime worker | ALLOW candidate | Worker uses durable jobs and locked append primitive; deployment/worker identity, schedule and runtime evidence pending |
| OP-01 | `scripts/migrate_postgres.py` | Operational/schema | ALLOW only via explicit migration role and approved deployment window | Source-reviewed; actual role, execution history and effective privileges not verified |
| OP-02 | `app/database.py` migration/schema routines | Operational/schema | ALLOW only through migration path | Source-level checks/locks/triggers documented; ownership, role separation and deployed schema unverified |
| QA-01 | `scripts/staging_rehearsal.py`, `scripts/staging_verify.py`, `deploy/staging/compose.yaml` | Disposable local staging | ALLOW test-only | Script claims isolated local Docker target and synthetic tenant; environment controls require independent confirmation |
| QA-02 | `workstation/OLA-Workstation.ps1`, `workstation/verify.ps1` | Operator workstation disposable Docker | ALLOW test-only | Source uses pinned source/signature, local loopback and test tenant; production reachability not attested |
| QA-03 | `scripts/state_continuity_runtime.py`, `scripts/verify_agent_runtime.py`, `scripts/verify_business_invoice.py`, `scripts/verify_decision_report.py`, `scripts/verify_nina_igor_gate.py`, `scripts/verify_nina_parallel_ollama.py`, `scripts/verify_provenance_runtime.py`, `scripts/verify_readme_claims.py`, `scripts/stress_runtime.py` | Local/CI verifier harnesses | ALLOW test-only when explicitly bound to disposable target | Inspect each invocation and target identity; these are verification tools, not permitted production writers |
| SEC-01 | `scripts/apply_main_ruleset.py` | Repository administration | NOT evidence writer | Changes GitHub repository ruleset (administrative side effect); separate authorization, not runtime evidence |
| SEC-02 | `scripts/check_codeql_sarif.py` | CI analysis | NOT evidence writer | Analysis/check helper; target and permissions must remain read-only |
| CI-01 | `.github/workflows/*.yml` (listed below) | GitHub Actions | ALLOW CI/test-only only | CI fixture writers use disposable DB/tenants; no workflow may be treated as production writer absent target/identity evidence |

## Workflow enumeration
Observed workflow files:
- `codeql.yml`, `decision-evidence-gate.yml`, `e2e.yml`, `evidence-cryptography-v4.yml`, `evidence-graph.yml`, `final-production-gate.yml`, `frontier-baseline.yml`, `igor-independent-evidence.yml`, `igor-independent-ollama-evidence.yml`, `jev-evaluation.yml`, `nina-igor-gate.yml`, `nina-igor-ollama.yml`, `nina-parallel-dag.yml`, `nina-real-runtime-provenance.yml`, `nina-tdd.yml`, `ola-12h-autoflow.yml`, `ola-24x7-watchdog.yml`, `ola-product-gate.yml`, `ola-workstation-installer-v2.yml`, `ollama-real-runtime.yml`, `paid-order-postgres.yml`, `provenance-gate-final.yml`, `provenance-mutation.yml`, `python-package-conda.yml`, `revenue-surface.yml`, `runtime-stress.yml`, `staging-rehearsal.yml`, `state-continuity.yml`, `supply-chain-evidence.yml`.
- CI mutation/seed hits identified in bounded search include `e2e.yml`, `ola-product-gate.yml`, `provenance-mutation.yml`, `provenance-gate-final.yml`, `nina-igor-ollama.yml`, `ollama-real-runtime.yml`, `nina-real-runtime-provenance.yml`, `igor-independent-evidence.yml`, and `igor-independent-ollama-evidence.yml`. The hits observed were fixture seeding/replay/tamper operations; they are not established production writer paths.
- Workflow trigger, schedule, permissions, secrets, deployment target and environment protections must be reviewed individually before each workflow is accepted into the allowlist. Tree enumeration alone is insufficient.

## Raw mutation/connection search findings
- `evidence_graph.py` appeared in search results with its own SQLite `nodes` persistence, not the `evidence_records` central evidence chain; classify as separate data store, not a central evidence writer.
- Test/verification code includes intentionally direct `EvidenceRecord` inserts and mutation probes; test context does not prove deployment isolation.
- `workstation/OLA-Workstation.ps1` and `scripts/staging_rehearsal.py` directly seed disposable SQLite tenants/keys for local Docker.
- No source search result establishes production reachability for these paths. This remains an external attestation requirement.

## Policy
1. The allowlist is explicit and version-controlled. Any writer path not listed, or whose target/identity/environment cannot be positively classified, is BLOCKED as a shadow writer.
2. Runtime evidence writes must resolve to the approved atomic writer contract (transaction, tenant lock, append-only integrity checks, commit/rollback) unless a path is specifically documented, tested and approved as a separately scoped writer.
3. CI, staging, workstation and migration paths must be separately credentialed and target-bounded; their mere presence in the repo does not prove isolation.
4. No blanket PASS is assigned to the runtime universe from this source inventory. Effective deployed identities, schedules, network reachability, DB grants, trigger state and production telemetry still require external attestation.
5. Status: REPOSITORY ENUMERATION = BOUNDED/PARTIAL; WRITER UNIVERSE COMPLETENESS = NOT PROVEN; PRODUCTION GO = NOT AUTHORIZED.
