# P0 Production Attestation Query Bundle

Run only under an approved read-only audit identity on the target production database. Do not execute remediation SQL or grant/revoke operations as part of evidence collection. Redact connection strings and secrets from outputs. Record query, timestamp, source system, principal, database, capture method and SHA-256 digest for each export.

## 1. Identity and connection context

```sql
SELECT current_database() AS database_name,
       current_user AS effective_user,
       session_user AS session_user,
       inet_server_addr() AS server_address,
       inet_server_port() AS server_port,
       current_setting('server_version') AS server_version,
       current_setting('ssl', true) AS ssl_setting;
```

The `ssl` setting is not necessarily a reliable connection TLS proof by itself; collect client-side connection details and infrastructure TLS policy as separate evidence.

## 2. Direct table privileges (effective user)

```sql
SELECT
  has_table_privilege(current_user, 'public.evidence_records', 'SELECT') AS can_select,
  has_table_privilege(current_user, 'public.evidence_records', 'INSERT') AS can_insert,
  has_table_privilege(current_user, 'public.evidence_records', 'UPDATE') AS can_update,
  has_table_privilege(current_user, 'public.evidence_records', 'DELETE') AS can_delete,
  has_table_privilege(current_user, 'public.evidence_records', 'TRUNCATE') AS can_truncate;
```

Repeat for explicitly qualified schema/table if deployment uses another schema.

## 3. Role memberships and role attributes

```sql
SELECT r.rolname, r.rolsuper, r.rolinherit, r.rolcreaterole,
       r.rolcreatedb, r.rolreplication, r.rolbypassrls, r.rolcanlogin
FROM pg_roles r
ORDER BY r.rolname;

SELECT member.rolname AS member_role, granted.rolname AS granted_role,
       m.admin_option
FROM pg_auth_members m
JOIN pg_roles member ON member.oid=m.member
JOIN pg_roles granted ON granted.oid=m.roleid
ORDER BY 1,2;
```

Review transitive membership, ownership, SET ROLE and escalation separately; a flat membership listing is not a complete effective-privilege calculation.

## 4. ACL inventory

```sql
SELECT table_schema, table_name, grantee, privilege_type, is_grantable
FROM information_schema.table_privileges
WHERE table_name='evidence_records'
ORDER BY table_schema, grantee, privilege_type;

SELECT n.nspname AS schema_name, p.privilege_type, p.grantee, p.is_grantable
FROM information_schema.schema_privileges p
JOIN pg_namespace n ON n.nspname=p.schema_name
WHERE n.nspname='public'
ORDER BY p.grantee, p.privilege_type;
```

Capture database, schema, table, sequence and function privileges; ownership and default ACLs are separate surfaces. Include sequences if evidence insertion uses them.

## 5. Trigger/function evidence

```sql
SELECT ns.nspname AS schema_name, c.relname AS table_name,
       t.tgname, t.tgenabled, pg_get_triggerdef(t.oid) AS trigger_definition,
       p.proname, pg_get_functiondef(p.oid) AS function_definition
FROM pg_trigger t
JOIN pg_class c ON c.oid=t.tgrelid
JOIN pg_namespace ns ON ns.oid=c.relnamespace
JOIN pg_proc p ON p.oid=t.tgfoid
WHERE NOT t.tgisinternal
  AND c.relname='evidence_records'
ORDER BY ns.nspname, t.tgname;
```

Verify who owns triggers/functions, whether the runtime role can alter/drop them, and whether any privileged function permits mutation. Trigger existence alone is not a privilege boundary.

## 6. Active connections (bounded snapshot)

```sql
SELECT usename, application_name, client_addr, client_port,
       backend_start, state, count(*) OVER (PARTITION BY usename, client_addr) AS grouped_count
FROM pg_stat_activity
WHERE datname=current_database()
ORDER BY backend_start;
```

A snapshot is not a complete historical source inventory. Obtain historical DB connection/audit logs and reconcile with deployment inventory.

## 7. Telemetry correlation export contract
- Freeze the population and time interval before sampling.
- Export from the database independently and from the telemetry/log system independently.
- Preserve committed append population and separately label failed/non-append attempts.
- Reconcile all event IDs (no unexplained unmatched records); sampling must not conceal population mismatches.
- Use cryptographically random sampling of at least 100 or all common IDs if population is smaller, with tenant/writer-type strata where applicable.
- Record DB and log export hashes, source identity, capture timestamp, query/filter, reviewer, and transfer integrity.
- Run the offline verifier on redacted JSONL exports; treat a verifier pass as consistency of supplied exports only, not authenticity/completeness.

## 8. Required external evidence
- Effective IAM policy export, role/identity binding, secret manager paths and access logs.
- Deployment inventory (API, workers, queue consumers, cron/scheduler, migration runners).
- Network allow/deny policy, routes/security groups/firewall, TLS evidence and authorized test results.
- CI/workstation secret scope and controlled reachability tests.
- Migration authorization, approvals, backup/restore evidence, rollback and concurrency policy.
- Evidence capture manifest with SHA-256 hashes and reviewer.

## Acceptance
Production gate remains blocked until every writer path and identity is classified, effective controls are verified, population is independently reconciled, zero unexplained mismatch/loss is demonstrated, and runtime locking/rollback tests pass on the candidate deployment.
