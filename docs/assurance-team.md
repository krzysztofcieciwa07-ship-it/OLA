# OLA Assurance Agent Team

## Purpose

The Assurance Agent Team performs sequential, read-only checks of an exact OLA source revision and emits an auditable report. The coordinator does not modify source, merge pull requests, deploy services, change access, or authorize production actions.

## Roles and activation

| Role | Responsibility | Initial status |
|---|---|---|
| Tester | Executes allowlisted runtime, safety, evidence, replay, NINA/IGOR and provider-boundary tests | Enabled |
| Architecture | Reviews package boundaries, imports, route/API contracts and architecture rules | Not enabled |
| Performance | Evaluates reproducible load and latency evidence | Not enabled |
| Protection | Reviews security boundaries, action permissions, dependency/secret and supply-chain evidence | Not enabled |
| Legal | Checks legal/compliance evidence inventory and reports missing or unverifiable controls | Not enabled |
| Orchestration | Runs enabled specialists in order, records lifecycle and aggregates outcomes | Coordinator enabled |

A role listed as not enabled has not run and is not passing. Each specialist must be implemented and tested before activation.

## Run locally

Install the repository's pinned requirements, then execute:

```bash
python -m pytest -q tests/test_assurance_team.py
python -m app.assurance_team.cli \
  --repo-root . \
  --source-commit "$(git rev-parse HEAD)" \
  --output-dir artifacts/assurance-team
```

The CLI rejects abbreviated or malformed commit identifiers and non-existent repository roots. The tester invokes only its fixed test-path allowlist using `shell=False` and a finite timeout.

## Evidence bundle

- `team-report.json` — source-bound aggregate status, specialist results, and coverage.
- `team-events.jsonl` — lifecycle events: `run.start`, paired `agent.start` / `agent.end`, and `run.end`.
- `team-evidence.sha256` — SHA-256 digests for the report and event stream.

Every event hash includes its predecessor hash and canonical event content. The independent verifier checks sequence numbers, one run boundary, matching specialist start/end events, and the hash chain. This detects post-generation tampering; it does not establish that an observation is factually true.

Raw pytest output is not copied to the evidence artifact. The tester records the output digest, recognized one-line summary, test paths, duration, exit code, and timeout.

## Status policy

- `PASS`: all checks run by that enabled specialist passed.
- `FAIL`: a check failed, timed out, or a specialist violated its contract.
- `BLOCKED`: a required tool or input was unavailable.
- `UNKNOWN`: available evidence cannot support a conclusion.
- Coverage is separately labelled `PARTIAL` until all planned specialist roles are enabled.

The overall status aggregates enabled specialists only. A partial coverage report cannot be described as a complete team assessment.

## Safety policy

The GitHub Actions workflow has `contents: read`, pinned actions, no production secrets, no deploy permissions, and a bounded runtime. Specialist agents are read-only. A security finding is not silently waived by the coordinator. Legal findings are control-gap observations, not legal advice or a compliance certification. Production deployment and release approval remain separate human decisions.
