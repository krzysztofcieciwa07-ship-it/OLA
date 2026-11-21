# P0 External Infrastructure Attestation & Telemetry Verification Package
Date: 2026-11-20
Repository: krzysztofcieciwa07-ship-it/OLA
Purpose: evidence collection package for DevOps/SRE; does not authorize production GO.

## Gate
Source review is insufficient. Obtain evidence from the live production environment and an independently controlled sampling process. Redact secrets, tokens, personal data and unsafe infrastructure details; preserve timestamps, account/project identifiers, provenance and reviewer identity.

## A. IAM / secret-scope attestation (required)
Provide secret manager and production scope/path for runtime DSN (never disclose value); workload principal and binding; access policy demonstrating secret is unavailable to CI, workstation/developer and migration-only identities except explicitly approved access; rotation policy and last rotation; migration credential identity/policy; effective DB role observed via live workload (for example current_user/session_user).

## B. Effective DB privilege proof (required)
Run with the actual production runtime identity, never output the DSN:
- SELECT current_user, session_user;
- SELECT current_database();
- SELECT has_table_privilege(current_user, 'public.evidence_records', 'SELECT'), has_table_privilege(current_user, 'public.evidence_records', 'INSERT'), has_table_privilege(current_user, 'public.evidence_records', 'UPDATE'), has_table_privilege(current_user, 'public.evidence_records', 'DELETE');
- Inspect TRUNCATE, schema privileges, inherited grants, role membership, ownership and escalation paths. Table privilege booleans alone are insufficient.
- Capture append-only trigger inventory and definitions, table owner, and proof that runtime cannot disable/drop triggers or alter schema/table.
- Demonstrate no CREATE/ALTER/DROP schema privileges, owner/superuser capability or privilege escalation.
Expected: least-privilege runtime identity, append-only enforcement, no escalation. Exceptions reopen P0.

## C. Network isolation proof (required)
Machine-readable exports of DB ingress/firewall/VPC/security-group rules, allowed runtime/migration sources, explicit denial/no route from CI/workstation/developer/untrusted networks, TLS requirement and certificate validation, plus authorized reachability test results. Include rule IDs, timestamps and account/project/region (redacted as needed). Prefer exports alongside screenshots.

## D. Migration authorization and controls (required)
Identify runner, principal, approval gate, invocation path and permissions; separate migration secret scope; backup/restore point; pre/post checks; concurrency/deployment lock; rollback/reconciliation procedure; enumerate alternate console, SQL, automation or owner paths. Advisory locks coordinate concurrency but do not prove authorization.

## E. Deterministic telemetry correlation
### Event key
Stable tuple where available: tenant_id, evidence_record_id, chain_sequence, record_hash, producer_id, source commit/version, append timestamp, operation/run ID. Telemetry records stable ID and outcome (success/failure/deduplicated/retry) without sensitive payloads.

### Sampling protocol
1. Define population independently: production append records/events for fixed UTC interval, tenants and writer sources; document retention/exclusions in advance.
2. Export population identifiers and hashes from DB and telemetry; do not choose from a single source.
3. Draw at least 100 records (or all if population <100) using documented cryptographically secure random sampling; independent reviewer. Stratify across tenant and writer types, document strata/inclusion probabilities.
4. Freeze sampled IDs before inspection; no replacement of missing or mismatching records.
5. For each i compare record R_i and log L_i against pre-defined fields: stable ID, tenant, sequence, hash, producer/source, outcome and timestamp tolerance.
6. Report all missing records/logs, mismatches, duplicates, retries, deduplication, sequence gaps and anomalies; no silent exclusions.
7. Report population/sample size, strata, sampling procedure/seed or commitment, selection date, reviewer, comparison script hash/version and redacted evidence manifest.

### Mathematical assertion
For each selected event i, require exact agreement on pre-defined fields: R_i = L_i. Sample passes only if forall i in S, match(R_i,L_i)=true, with zero unexplained mismatches. This proves sampled consistency, not absolute population completeness. Completeness also requires writer enumeration, population definition, retention/loss controls and reconciliation of event classes.

Suggested metrics: DB append by writer/tenant/window; log outcome by writer/tenant/window; missing log/DB event; duplicate correlation ID; sequence gap; hash mismatch; latency/timestamp skew. Count equality is not a pass condition.

## F. Workstation/CI reachability proof
Inventory workstation scripts/identities/secrets/environment scopes; CI secret scopes/deployment controls; show CI test DB is distinct from production. Authorized tests from workstation and CI runner to production DB should show blocked reachability or documented exception. Verify workstation bootstrap/verification scripts cannot implicitly switch to production.

## G. Attestation manifest
Capture environment/account/project/region (redacted), UTC capture timestamps, deployed source commit and artifact/image digest, DB engine/version and identities (not credentials), reviewer/approver roles, evidence filenames and SHA-256 checksums, findings/exceptions/remediation owner/expiry.

## H. Acceptance
P0 remains OPEN until A-F are independently evidenced and reviewed, sampled correlation is zero-mismatch, and writer enumeration is reconciled against deployed identities and network access. This package is not evidence that any item is already completed.
Production GO: NOT AUTHORIZED.
