# OLA DI-OS: truthful local diagnostics and execution evidence

## What is implemented

- `scripts/ola_truth_cycle.py` hashes a bounded source inventory before and after a
  real pytest run, reads its JUnit XML, inspects source-to-Git binding, and writes
  one unique JSON report without overwriting previous reports.
- Evidence gives `PASS` only if pytest exits successfully, JUnit is structurally
  readable, at least one test executed, and no failures/errors were reported.
  All-skipped and missing evidence are `UNKNOWN`; source mutation blocks success.
- The CLI exits successfully only if local tests passed and the configured source
  scope matches Git `HEAD`. `NO_GO`/`PENDING_HUMAN` applies even then.
- Each report includes a canonical SHA-256 digest. This checks accidental or
  uncoordinated changes, **not** the identity of the author or authenticity.
- `app/truth_contract.py` distinguishes real LLM invocations, deterministic
  simulations, and trace integrity. Without an independent verifier,
  `answer_correctness` is always `UNKNOWN`.
- `/agent-run` has a fail-closed LOW/HIGH gate, bound request profile, input
  validation, and a truth statement. The profile is not an individual runtime
  actor; the actual local runtime follows six predefined roles.
- The 391-profile digest demo identifies itself as `SIMULATED`, with no real
  LLM invocations, independently confirmed collaboration, or agent messages.
- The paid Stripe path persists and exposes the runtime truth statement. If
  runtime evidence verification fails, payment remains confirmed but the audit
  is reported as `EXECUTION_BLOCKED`, never `COMPLETED`.

## How to run locally

From the repository root with installed dependencies:

```bash
python scripts/ola_truth_cycle.py --repo . --output-dir ./ola_truth_reports --timeout 180
python scripts/ola_truth_cycle.py --verify-report ./ola_truth_reports/cycle_<id>.json
```

Use the actual generated report path in the second command. The cycle runs the
test suite in a subprocess with configured model/payment credentials omitted.
It does **not** call external AI APIs, apply mutations, back up source, roll back
changes, or authorize releases. A dirty/untracked/ignored/linked scoped source
tree makes the CLI exit nonzero, even if tests pass.

## Exact evidence boundaries

| Claim | What the proof supports | What it does not support |
|---|---|---|
| `local_test_status=PASS` | The selected pytest suite passed locally, without detected scoped source changes | General correctness, adversarial resilience, live integration, customer acceptance |
| `source_bound_to_commit=true` | Hashable non-symlink files in the enumerated scope are tracked and unchanged at `HEAD` | Full filesystem, RAM, environment variables, installed dependencies, remote deployment |
| `evidence_integrity=VERIFIED` | The recorded hash-chain integrity check passed | Factual truth, semantic correctness, independent fact checking |
| `SIMULATED` 391 profiles | Deterministic in-memory digest graph has valid structural relationships | 391 independent executing LLM agents or verified communication |
| `report_sha256` | The current report content hashes to the included digest | Tamper-resistant signature; author identity; trusted timestamp |

Source scope: `app/`, `tests/`, `scripts/`, `.github/workflows/`, `web/`,
`revenue/`, `workstation/`, plus selected root runtime/test configuration files.
No files outside this scope are hashed. Symlinks in scope are not followed and
prevent a claim that the source is fully bound to a commit.

## Known limitations / open production gates

1. There is no independently operating factual-answer verifier or measured
   improvement benchmark, so claims such as "10x smarter" are unsupported.
2. CI and local tests are different from a live commercial E2E transaction;
   payments and model-provider calls are not exercised with production accounts.
3. There is no real rollback backup, signed attestation service, reliable
   long-running autonomous mutation engine, or unattended promotion workflow.
4. A passing GitHub workflow is necessary diagnostic evidence, not Human Gate
   approval. Operators must separately review customer scope, access controls,
   production secrets, release identity, and actual deployment evidence.
5. Reports accumulate. Retention/archival and independent verification must be
   configured by a trusted operator; this tool never silently deletes reports.

**Production decision is always `NO_GO / PENDING_HUMAN`.**
