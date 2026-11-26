# Branch Risk Report: duplicate agent-runtime branches

## Scope
This report covers only repository cleanup. It does not create a second runtime, add product functionality, or replace the existing system.

## Branches assessed
All branches below point to the same HEAD commit:

`c87cb3c8a798fece4ee18f73ecc648e397b23c24`

- `fix/agent-runtime-minimal-2`
- `fix/agent-runtime-minimal-3`
- `fix/agent-runtime-minimal-4`
- `fix/agent-runtime-minimal-5`
- `fix/agent-runtime-minimal-7`
- `fix/agent-runtime-minimal-8`
- `fix/agent-runtime-minimal-9`
- `fix/agent-runtime-minimal-10`
- `fix/agent-runtime-minimal-11`

## Commit reachability
The exact commit is returned by commit search scoped to the default branch. The current `main` also contains `tests/test_agent_runtime.py`, and its current blob is a later, materially expanded version of the file introduced by the assessed commit.

Assessment: `REACHABLE / SUPERSEDED IN MAIN`.

## Unique files and tests
The assessed commit added one file only:

- `tests/test_agent_runtime.py`
- 71 additions
- three initial contract tests covering ordered six-agent verification, missing evidence rejection, and the `/agent-run` endpoint.

Current `main` contains the same path with an evolved test suite. It preserves those original areas and adds source-commit binding, fail-closed behavior, execution identity/context checks, deterministic-mode network blocking, lifecycle evidence, input limits, provider endpoint restrictions, allowlisting, and failure handling.

No unique file path from the assessed commit is absent from current `main`.

Assessment: `NO UNIQUE FILE REQUIRING SALVAGE`.

## Pull request dependencies
Repository PR search returned no pull request whose head is any of the nine assessed branch names.

Assessment: `NO DIRECT PR DEPENDENCY FOUND`.

## Risk assessment
- Code-loss risk: LOW. All nine names resolve to one identical commit.
- Test-loss risk: LOW. The introduced test path exists on current `main` in a broader form.
- Security/evidence risk: LOW. The current test file includes stricter fail-closed and provenance/source-binding checks.
- Migration risk: NONE IDENTIFIED. The assessed commit changed only `tests/test_agent_runtime.py`.
- CI/workflow risk: NONE IDENTIFIED. The assessed commit changed no workflow file.
- Documentation risk: NONE IDENTIFIED. The assessed commit changed no documentation file.
- PR/reference risk: LOW. No direct PR dependency was found for the assessed branch names.
- Rollback risk: LOW. The commit SHA remains recorded in this report and Git history.

## Disposition
Decision for all nine branches: `DELETE-VERIFIED`.

The branch names are redundant references to the same commit, and the commit's only file is represented and expanded on current `main`. No salvage commit is required.

## Deletion condition
Delete only the branch references. Do not rewrite Git history and do not modify `main` as part of deleting these references.
