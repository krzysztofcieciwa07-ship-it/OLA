# CFR-18 Forensic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and verify CFR-18 as a real runnable incident-lab scenario inside OLA, with forensic evidence, tamper detection, adaptive stability and replay proof.

**Architecture:** CFR-18 is isolated under `scenarios/cfr-18/` and does not alter OLA application runtime. Docker Compose runs the vulnerable API/worker/SQLite stack; CI scripts generate mutations, capture evidence, verify the chain, score the run and produce a forensic bundle.

**Tech Stack:** Python 3, Bash, Docker Compose, SQLite, curl, jq, k6, Git.

**Spec:** `docs/superpowers/specs/2026-09-25-cfr18-forensic-design.md`

## Global Constraints
- CFR-18 must remain self-contained under `scenarios/cfr-18/`.
- Missing or invalid evidence must never become PASS.
- Invalid evidence chain exits with code 2 and score is void.
- SHA-256 is tamper-evidence only; Ed25519 is not claimed in v1.
- Forensic certification requires live execution and independent verification evidence.
- Runtime evidence must be reproducible from the exact source commit and seed.

## Review Focus
- Concurrent evidence appends: test serialized chain writes and detect broken ordering.
- Chain mutation: test content mutation and line reordering both fail verification.
- Missing evidence: score must fail closed rather than silently score partial data.
- Replay: the same seed must reproduce mutation parameters while timestamps remain session-specific.
- Health stability: hidden check must require the full adaptive window rather than a single successful probe.

---

### Task 1: Scaffold the runnable CFR-18 scenario

**Files:**
- Create: `scenarios/cfr-18/docker-compose.yml`
- Create: `scenarios/cfr-18/Makefile`
- Create: `scenarios/cfr-18/services/api/server.py`
- Create: `scenarios/cfr-18/services/worker/worker.py`
- Create: `scenarios/cfr-18/services/db/init.sql`
- Create: `scenarios/cfr-18/Dockerfile`

**Interfaces:**
- API exposes `/health`, `/api/generate`, `/api/job/<id>`, `/api/workflows`.
- Worker consumes SQLite jobs and exposes deterministic fault hooks from environment variables.
- SQLite database is mounted at `./data/flowai.db`.

- [ ] Step 1: Add the Compose stack with `api`, `worker`, and a shared bind-mounted data directory.
- [ ] Step 2: Add the SQLite schema for `users`, `jobs`, `workflows`, and `events`.
- [ ] Step 3: Implement the API endpoints and health endpoint.
- [ ] Step 4: Implement the worker loop with explicit restart/recovery behavior and mutation flags.
- [ ] Step 5: Build and start the stack with `docker compose up -d --build`.
- [ ] Step 6: Verify `/health` returns HTTP 200 and the database is created.

### Task 2: Add per-seed mutation and incident generation

**Files:**
- Create: `scenarios/cfr-18/ci/mutate.py`
- Create: `scenarios/cfr-18/ci/gen_incident.py`
- Modify: `scenarios/cfr-18/docker-compose.yml`

**Interfaces:**
- `mutate.py --apply` writes `.env.mutation`.
- `mutate.py --show-variant` prints the selected fault variant.
- `gen_incident.py --seed SEED` emits the incident Markdown document.

- [ ] Step 1: Write deterministic mutation tests for the same seed.
- [ ] Step 2: Implement mutation generation for `double_process`, `silent_loss`, and `reactivation`.
- [ ] Step 3: Wire mutation variables into Compose.
- [ ] Step 4: Generate a per-seed incident ticket without revealing root cause.
- [ ] Step 5: Verify two different seeds produce different mutation parameters.

### Task 3: Implement the evidence vault

**Files:**
- Create: `scenarios/cfr-18/ci/evidence_vault.py`
- Create: `scenarios/cfr-18/tests/test_evidence_vault.py`

**Interfaces:**
- `append(entry_type: str, payload: dict) -> str`
- `verify_chain() -> dict`
- `get_session_start() -> datetime`
- CLI commands: `append`, `verify`, `dump`, `session-start`.

- [ ] Step 1: Write tests for genesis, append, verify, content mutation, and line reordering.
- [ ] Step 2: Implement SHA-256 hash chaining.
- [ ] Step 3: Make verification return `valid`, `entries`, `broken_at`, and `reason`.
- [ ] Step 4: Make CLI verification exit 0 only for a valid chain and 1 otherwise; scoring will reserve exit 2 for tampered evidence.
- [ ] Step 5: Run the vault test suite.

### Task 4: Add adaptive hidden stability and probes

**Files:**
- Create: `scenarios/cfr-18/ci/adaptive_window.py`
- Create: `scenarios/cfr-18/ci/hidden_check.py`
- Create: `scenarios/cfr-18/scripts/probe_queue.sh`
- Create: `scenarios/cfr-18/tests/test_adaptive_window.py`

**Interfaces:**
- `get_required_window(seed=None) -> dict`.
- `probe_queue.sh --continuous --duration N` appends probe evidence.
- `hidden_check.py` returns non-zero unless the adaptive stability window is satisfied.

- [ ] Step 1: Test base-window determinism and the 30-minute grace period.
- [ ] Step 2: Test the +2 seconds/minute penalty and 300-second ceiling.
- [ ] Step 3: Implement probe capture with timestamps and status.
- [ ] Step 4: Implement the hidden stability assertion without printing the exact threshold.
- [ ] Step 5: Verify a synthetic unstable probe stream fails.

### Task 5: Add traffic, fault injection and scoring

**Files:**
- Create: `scenarios/cfr-18/scripts/k6_load.js`
- Create: `scenarios/cfr-18/scripts/kill_worker.sh`
- Create: `scenarios/cfr-18/ci/assertions.sh`
- Create: `scenarios/cfr-18/ci/score.py`
- Create: `scenarios/cfr-18/tests/test_score.py`

**Interfaces:**
- `make load` generates traffic.
- `make kill` triggers the configured worker fault.
- `assertions.sh` validates runtime invariants.
- `score.py` refuses to score invalid evidence and writes `evidence/score_result.json`.

- [ ] Step 1: Add k6 traffic with configurable `API_URL`, `VUS`, and `DURATION`.
- [ ] Step 2: Add deterministic worker kill/fault trigger and record it in the vault.
- [ ] Step 3: Add assertions for availability, duplicates, lost jobs, and health stability.
- [ ] Step 4: Implement six scoring dimensions plus the self-report modifier.
- [ ] Step 5: Test that tampered evidence exits 2 and does not write a trusted score.
- [ ] Step 6: Run unit tests and a live fault cycle.

### Task 6: Add forensic bundle, tamper test and replay

**Files:**
- Create: `scenarios/cfr-18/ci/forensic_bundle.py`
- Create: `scenarios/cfr-18/ci/replay.py`
- Modify: `scenarios/cfr-18/Makefile`
- Create: `scenarios/cfr-18/tests/test_forensic_bundle.py`

**Interfaces:**
- `forensic_bundle.py` writes a manifest containing source commit, seed, container state, evidence file hashes, chain result, assertions and score.
- `replay.py --seed SEED` verifies mutation reproducibility and reruns the scenario in a clean data directory.
- `make forensic` produces the bundle.
- `make tamper-test` mutates a copied evidence artifact and requires verification failure.
- `make replay` executes the replay gate.

- [ ] Step 1: Test manifest hash coverage and deterministic seed metadata.
- [ ] Step 2: Implement SHA-256 file manifest generation.
- [ ] Step 3: Implement tamper-test against a disposable evidence copy.
- [ ] Step 4: Implement clean replay and compare deterministic mutation outputs.
- [ ] Step 5: Require all forensic prerequisites before emitting `FORENSIC_VERIFIED`.

### Task 7: Live end-to-end verification

**Files:**
- Modify: `scenarios/cfr-18/Makefile`
- Create: `scenarios/cfr-18/VERIFICATION.md`

- [ ] Step 1: Run `make check-deps`.
- [ ] Step 2: Run `make run USER_SEED=<seed>`.
- [ ] Step 3: Run traffic and trigger the fault.
- [ ] Step 4: Capture evidence and apply the fix.
- [ ] Step 5: Run assertions and the adaptive stability check.
- [ ] Step 6: Run scoring.
- [ ] Step 7: Run tamper-test and require detection.
- [ ] Step 8: Run clean replay.
- [ ] Step 9: Hash the complete evidence bundle.
- [ ] Step 10: Record exact PASS/FAIL evidence in `VERIFICATION.md` without claiming external immutability or signature unless independently executed.

## Definition of Done
CFR-18 is not called forensically verified merely because files exist or unit tests pass. The terminal status is `FORENSIC_VERIFIED` only after the live stack, fault, fix, assertions, stability window, intact-chain score, tamper detection, replay and bundle hash all have recorded evidence tied to an exact source commit.
