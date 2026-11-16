# OLA E2.2 — PostgreSQL RED baseline evidence

**Date:** 2026-11-16  
**Repository:** `krzysztofcieciwa07-ship-it/OLA`  
**Branch:** `security/e2-2-tenant-context-implementation-20261116`  
**Draft PR:** [#237](https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/237)  
**Test candidate SHA:** `290663f9b5b5f3dbe331d6f10a41c93831be3b8a`  
**Workflow:** [OLA paid-order PostgreSQL contract #826](https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/43935846340)  
**Job ID:** `133540088692`

## Exact result

The workflow checked out the exact candidate SHA (checkout assertion passed), installed dependencies, started PostgreSQL 17, and ran:

```sh
python -m pytest -q -o addopts='' tests/test_database_postgres_support.py tests/test_postgres_integration.py
```

Result: **19 passed, 2 failed in 6.53s**.

The two failures are the intended E2.2 RED regressions:

1. `test_postgres_runtime_cannot_spoof_tenant_guc_to_read_other_tenant` failed because `ola_runtime` could still set `ola.tenant_id` and read a tenant row. This reproduces the security defect against the current implementation.
2. `test_postgres_trusted_api_key_context_overrides_forged_guc` failed because `ola_establish_api_key_context(text)` does not yet exist.

The other 19 PostgreSQL contract tests passed on this exact candidate SHA. This is a baseline measurement, not a successful security acceptance.

## Interpretation

- The GUC spoof is confirmed against the real PostgreSQL 17 CI service.
- The existing E2.1 tests remain green at the RED baseline.
- The implementation must add the database-verified context and replace GUC-based RLS predicates; weakening or skipping either regression is prohibited.
- The next GREEN gate must run the same suite against a new exact candidate SHA and show both regressions passing without reducing the existing E2.1 coverage.

## Scope and safety

No production database was migrated. No Railway deployment, payment operation, merge, or change to PR #234 was performed. PR #237 remains Draft.
