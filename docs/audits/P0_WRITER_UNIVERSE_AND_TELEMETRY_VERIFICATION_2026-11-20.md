# P0 Writer Universe & Executable Telemetry Verification

This verifier works only on locally supplied, redacted JSONL exports; it has no DB/network access and does not attest export completeness/authenticity.

## Candidate writer universe to reconcile with infrastructure
| Category | Candidate | Required evidence |
|---|---|---|
| Tenant API | routes/handlers | deployed route map, workload identity, DB role |
| Central writer | atomic writer wrapper | caller enumeration and telemetry |
| Direct locked writers | workflow/order/report/review/execution modules | deployed code, lock/transaction and telemetry |
| Migration CLI/jobs | migration script and orchestration | runner, identity, authorization, secret scope |
| CI workflows | GitHub Actions | permissions, secrets, runner/network, DB target |
| Cron/schedulers | cloud scheduler/cron/queue tasks | infra inventory and identity |
| Workers | queue consumers/async deployments | manifests, identity, DB access |
| Management consoles | cloud console, admin UI, bastion, SQL clients | role/access logs/policy/network |
| Workstation scripts | PowerShell and local tools | effective credentials, reachability, policy |
| External integrations | third-party automation | source inventory, credentials and route |
| Alternate paths | raw SQL, dynamic SQL, DB owner/superuser | privileges and containment evidence |

Unclassified DB-capable path is a shadow path and fails completeness. This is a candidate list, not an assertion of exhaustiveness.

## Export format
JSONL (one object per line), fields: `event_id`, `tenant_id`, `record_id`, `sequence`, `record_hash`, `producer_id`, `outcome`, `timestamp` (Unix seconds).

## Usage
`python3 scripts/audits/verify_telemetry_correlation.py --db-jsonl db_export.jsonl --logs-jsonl logs_export.jsonl --sample-size 100 --manifest sample_manifest.json`

`--sample-size 0` compares the full shared-ID set. The script reports missing/orphan IDs and sampled field/time mismatches. Exit code 2 means mismatch or unmatched IDs. Zero means the supplied exports matched on the comparison performed; it does not authenticate or prove export completeness.

## Loss policy
**Zero unexplained loss** for the defined population. Do not waive mismatches via percentage tolerance. Define population, exclusions, retries, deduplication, failure semantics and retention before freezing exports. Distinguish failed/non-append attempts from committed appends. Sample consistency and completeness are different claims.

## Negative proof
Bounded negative proof requires inventory of all DB-capable identities, roles, jobs, network sources, secret scopes and management paths, plus effective controls that constrain them. Repository search cannot alone prove absence of production shadow writers.
