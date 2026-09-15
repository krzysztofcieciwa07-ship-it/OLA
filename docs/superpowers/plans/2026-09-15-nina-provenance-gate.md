# NINA → IGOR → HUMAN Provenance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and prove the product-layer NINA → IGOR → HUMAN provenance gate without weakening the verified OLA runtime baseline.

**Architecture:** Add focused provenance-domain modules around the existing runtime rather than replacing the verified OLA evidence/hash-chain substrate. NINA creates immutable candidate/provenance records; IGOR independently recomputes integrity, lineage and contradictions; the Gate produces VERIFIED/REVIEW/BLOCK/UNKNOWN; HUMAN authorization and replay are separate records. CI runs the product E2E and a standalone verifier against captured runtime evidence.

**Tech Stack:** Python 3.13, existing application modules, pytest, SHA-256, append-only hash chain, Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-15-nina-igor-human-provenance-gate.md`

## Global Constraints

- Evidence-first: no PASS without runtime evidence and independent verification.
- Preserve existing verified OLA E2E behavior.
- NINA must never self-certify.
- IGOR verification must be independently recomputed.
- `UNKNOWN → VERIFIED` is forbidden.
- Unresolved contradiction → `REVIEW`.
- Missing mandatory provenance/integrity → `BLOCK` or `UNKNOWN` according to the explicit rule.
- Human authorization is separate from AI verification.
- Replay must reproduce the recorded gate outcome.
- Deterministic local runtime is not presented as external production LLM inference.

---

### Task 1: Provenance domain contract

**Files:**
- Create: `app/provenance.py`
- Test: `tests/test_provenance_contract.py`

**Interfaces:**
- Produces typed records/functions for task, claim, source, raw artifact, extraction, evidence and correlation records.
- Produces canonical serialization and SHA-256 calculation used by later verifier tasks.

- [ ] **Step 1: Write failing tests**

```python
def test_artifact_hash_is_deterministic():
    artifact = RawArtifact(artifact_id="a1", content=b"hello", captured_at="2026-09-15T00:00:00Z")
    assert artifact.sha256 == sha256_bytes(b"hello")


def test_claim_requires_source_reference():
    claim = Claim(claim_id="c1", task_id="t1", content="fact", source_id=None)
    assert claim.is_provable is False
```

- [ ] **Step 2: Run the focused test and verify it fails because the contract is absent**

Run: `pytest tests/test_provenance_contract.py -q`
Expected: FAIL with import/attribute errors for the new provenance contract.

- [ ] **Step 3: Implement the minimal contract**

Implement immutable dataclasses for `TaskRecord`, `ClaimRecord`, `SourceRecord`, `RawArtifact`, `ExtractionRecord`, `EvidenceRecord`, and `CorrelationRecord`. Use canonical JSON (`sort_keys=True`, stable UTF-8 encoding) and `hashlib.sha256` for artifact hashes. Do not add network fetching or external model calls.

- [ ] **Step 4: Run the focused test**

Run: `pytest tests/test_provenance_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/provenance.py tests/test_provenance_contract.py
git commit -m "feat: add provenance domain contract"
```

### Task 2: NINA candidate result and append-only provenance ledger

**Files:**
- Create: `app/nina_runtime.py`
- Create: `app/provenance_ledger.py`
- Test: `tests/test_nina_provenance.py`

**Interfaces:**
- `NinaRuntime.create_candidate(task_input: str) -> CandidateResult`
- `ProvenanceLedger.append(record) -> LedgerRecord`
- `ProvenanceLedger.verify_chain() -> bool`
- Produces `candidate.json`-equivalent structured data with task, claims, sources, artifacts, hashes, extraction and evidence references.

- [ ] **Step 1: Write failing tests for candidate creation and ledger chaining**

```python
def test_nina_creates_candidate_bound_to_task():
    candidate = NinaRuntime().create_candidate("verify 2+2")
    assert candidate.task.task_id
    assert candidate.claims
    assert candidate.status == "CANDIDATE"


def test_ledger_is_append_only_and_hash_chained():
    ledger = ProvenanceLedger()
    ledger.append({"type": "task.received", "task_id": "t1"})
    ledger.append({"type": "candidate.created", "task_id": "t1"})
    assert ledger.verify_chain() is True
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_nina_provenance.py -q`
Expected: FAIL because the NINA runtime and ledger do not yet exist.

- [ ] **Step 3: Implement minimal NINA candidate generation**

Wrap the existing deterministic execution substrate without claiming external LLM inference. Every generated candidate gets a task ID, claim ID, source ID, raw artifact bytes, SHA-256, extraction record, evidence ID and correlation ID. NINA may write `CANDIDATE` but must not write an IGOR `VERIFIED` result.

- [ ] **Step 4: Implement append-only ledger**

Store canonical records with sequence number, previous hash, current hash and timestamp. Reject mutation/deletion attempts and make `verify_chain()` recompute every hash.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_nina_provenance.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/nina_runtime.py app/provenance_ledger.py tests/test_nina_provenance.py
git commit -m "feat: add nina candidate provenance ledger"
```

### Task 3: IGOR independent verifier

**Files:**
- Create: `app/igor_verifier.py`
- Create: `scripts/verify_nina_provenance.py`
- Test: `tests/test_igor_verifier.py`

**Interfaces:**
- `IgorVerifier.verify(candidate, ledger) -> VerificationResult`
- `scripts/verify_nina_provenance.py` reads persisted evidence and exits 0 only for a recomputed valid result.

- [ ] **Step 1: Write failing tests**

```python
def test_igor_rejects_missing_source():
    candidate = valid_candidate_without_source()
    result = IgorVerifier().verify(candidate)
    assert result.status == "BLOCK"


def test_igor_does_not_trust_nina_status():
    candidate = valid_candidate()
    candidate.nina_status = "VERIFIED"
    result = IgorVerifier().verify(candidate)
    assert result.verified_by == "IGOR"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_igor_verifier.py -q`
Expected: FAIL because the independent verifier does not exist.

- [ ] **Step 3: Implement independent recomputation**

IGOR must independently recompute raw-artifact SHA-256, ledger hash chain, required provenance links, claim/evidence correlations and mandatory fields. It must not call a NINA verification function or trust a NINA status field.

- [ ] **Step 4: Implement standalone verifier**

The script must load the persisted candidate/ledger data, perform the same checks independently of `IgorVerifier`, print a structured result, and exit 1 for any invalid, missing or unresolved required condition.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_igor_verifier.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/igor_verifier.py scripts/verify_nina_provenance.py tests/test_igor_verifier.py
git commit -m "feat: add independent igor provenance verifier"
```

### Task 4: Contradiction Engine and Provenance Gate

**Files:**
- Create: `app/contradiction_engine.py`
- Create: `app/provenance_gate.py`
- Test: `tests/test_provenance_gate.py`

**Interfaces:**
- `ContradictionEngine.detect(claims, evidence) -> list[Conflict]`
- `ProvenanceGate.evaluate(verification, conflicts, policy) -> GateResult`

- [ ] **Step 1: Write failing tests for contradiction and state transitions**

```python
def test_unresolved_conflict_produces_review():
    result = gate_with_conflict()
    assert result.status == "REVIEW"


def test_unknown_cannot_become_verified():
    result = force_unknown_then_verify()
    assert result.status != "VERIFIED"


def test_missing_artifact_blocks():
    result = gate_with_missing_artifact()
    assert result.status == "BLOCK"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_provenance_gate.py -q`
Expected: FAIL because contradiction and gate modules do not exist.

- [ ] **Step 3: Implement contradiction detection**

Compare claims/evidence for incompatible normalized values on the same task and emit stable conflict IDs with the involved claim/evidence IDs. Do not infer contradiction from stylistic differences alone.

- [ ] **Step 4: Implement fail-closed gate**

Apply the specified precedence: integrity/provenance violations → `BLOCK`; unresolved contradictions → `REVIEW`; insufficient evidence → `UNKNOWN`; only complete independently verified evidence may yield `VERIFIED`.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_provenance_gate.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/contradiction_engine.py app/provenance_gate.py tests/test_provenance_gate.py
git commit -m "feat: add contradiction engine and provenance gate"
```

### Task 5: HUMAN decision boundary and replay

**Files:**
- Create: `app/human_gate.py`
- Create: `app/replay.py`
- Test: `tests/test_human_gate_replay.py`

**Interfaces:**
- `HumanGate.record_decision(gate_result, decision, actor) -> HumanDecision`
- `ReplayEngine.replay(ledger) -> ReplayResult`

- [ ] **Step 1: Write failing tests**

```python
def test_human_decision_is_separate_from_igor_verification():
    decision = HumanGate().record_decision(verified_result(), "APPROVE", "human")
    assert decision.actor == "human"
    assert decision.decision == "APPROVE"
    assert decision.verification_id


def test_replay_reproduces_gate_outcome():
    result = ReplayEngine().replay(known_good_ledger())
    assert result.reproduced_status == "VERIFIED"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_human_gate_replay.py -q`
Expected: FAIL because human gate and replay do not exist.

- [ ] **Step 3: Implement explicit human decision record**

Permit `APPROVE` or `REJECT` only after an IGOR result exists. Record actor, timestamp, gate/verification ID and decision in the append-only ledger. Do not alter IGOR's result.

- [ ] **Step 4: Implement deterministic replay**

Reconstruct the task-to-decision chain from ledger records, recompute hashes and gate semantics, and report whether the recorded outcome is reproducible. Replay must fail if the chain is tampered with.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_human_gate_replay.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/human_gate.py app/replay.py tests/test_human_gate_replay.py
git commit -m "feat: add human gate and deterministic replay"
```

### Task 6: Product E2E proving the complete chain

**Files:**
- Create: `tests/test_nina_igor_human_e2e.py`
- Modify: `app/main.py`
- Modify: `tests/test_e2e.py`

**Interfaces:**
- Product endpoint exposes a candidate plus provenance references; verification and human decision are represented as separate records.
- E2E asserts actual records, not only HTTP status.

- [ ] **Step 1: Write the failing E2E assertion**

```python
def test_full_nina_igor_human_chain(client):
    response = client.post("/audit", json={"task": "verify 2+2"})
    body = response.json()
    assert body["gate"]["status"] == "VERIFIED"
    assert body["verification"]["verified_by"] == "IGOR"
    assert body["provenance"]["artifact_sha256"]
    assert body["human_decision"]["decision"] == "APPROVE"
    assert body["replay"]["reproduced"] is True
```

- [ ] **Step 2: Run the new E2E and verify failure**

Run: `pytest tests/test_nina_igor_human_e2e.py -q`
Expected: FAIL until the endpoint exposes the complete chain.

- [ ] **Step 3: Integrate the minimum endpoint flow**

Route the task through NINA candidate creation, IGOR verification, gate evaluation, explicit human decision for the test policy, and replay. Preserve the existing endpoint contract used by the verified OLA tests.

- [ ] **Step 4: Run focused and legacy E2E tests**

Run: `pytest tests/test_nina_igor_human_e2e.py tests/test_e2e.py -q`
Expected: PASS with legacy tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_e2e.py tests/test_nina_igor_human_e2e.py
git commit -m "feat: prove nina igor human product e2e"
```

### Task 7: Runtime evidence artifact and CI independent gate

**Files:**
- Modify: `.github/workflows/e2e.yml`
- Create: `scripts/capture_nina_provenance.py`
- Create: `scripts/verify_nina_provenance.py` if Task 3 requires final CLI refinement
- Test: `tests/test_runtime_provenance_artifact.py`

**Interfaces:**
- Capture script writes a commit-bound runtime evidence bundle.
- CI runs the product E2E, captures the bundle, then invokes the standalone verifier against the captured bundle.

- [ ] **Step 1: Write artifact contract tests**

```python
def test_runtime_artifact_contains_commit_and_hashes(tmp_path):
    artifact = capture_runtime_proof(tmp_path, commit_sha="8b8ea418c9f0f45b0696749e72ed5bc00c1aaf0c")
    assert artifact["commit_sha"]
    assert artifact["ledger_sha256"]
    assert artifact["gate_status"] in {"VERIFIED", "REVIEW", "BLOCK", "UNKNOWN"}
```

- [ ] **Step 2: Run and verify failure**

Run: `pytest tests/test_runtime_provenance_artifact.py -q`
Expected: FAIL until capture is implemented.

- [ ] **Step 3: Implement capture**

Capture the exact commit SHA, task/candidate IDs, ledger, verification, gate, human decision and replay result. Hash the bundle and write a manifest.

- [ ] **Step 4: Add CI execution order**

The workflow must run: pytest → application/runtime E2E → capture artifact → standalone IGOR verifier → upload artifact. The workflow must exit non-zero if the verifier exits non-zero. Existing OLA E2E checks remain in place.

- [ ] **Step 5: Run local verification**

Run: `pytest -q`
Run: `python scripts/verify_nina_provenance.py <captured-artifact>`
Expected: all tests PASS and verifier exits 0 only when the evidence is valid.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/e2e.yml scripts/capture_nina_provenance.py tests/test_runtime_provenance_artifact.py
git commit -m "ci: gate nina provenance with runtime evidence"
```

### Task 8: Tamper/failure matrix and final verification

**Files:**
- Create: `tests/test_provenance_failure_matrix.py`
- Modify: `scripts/verify_nina_provenance.py`
- Modify: `.github/workflows/e2e.yml`

**Interfaces:**
- Independent verifier returns deterministic non-zero status for each invalid state.

- [ ] **Step 1: Write failure-injection tests**

Cover: missing source, missing raw artifact, SHA mismatch, orphan claim, tampered ledger, unresolved contradiction, missing verifier output, and attempted `UNKNOWN → VERIFIED` transition.

- [ ] **Step 2: Run tests and verify any missing failure paths**

Run: `pytest tests/test_provenance_failure_matrix.py -q`
Expected: FAIL for each not-yet-implemented guard.

- [ ] **Step 3: Implement only the minimal guards required by failing tests**

Each guard must produce a specific failure reason and a non-zero verifier exit status. Do not add permissive fallback behavior.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS with zero failures.

- [ ] **Step 5: Run the standalone verifier against a real captured runtime bundle**

Run: `python scripts/verify_nina_provenance.py <real-runtime-bundle>`
Expected: exit 0 and print a recomputed `VERIFIED` result with commit binding and hash-chain validation.

- [ ] **Step 6: Push branch and inspect GitHub Actions**

Push `feat/nina-provenance-gate` and wait for the workflow to finish. Record the exact commit SHA, run ID, job, artifact name, artifact digest and verifier output.

- [ ] **Step 7: Only after all evidence is present, classify the result**

`VERIFIED` requires: full test suite pass, CI success, runtime evidence artifact present and commit-bound, standalone verifier exit 0, and replay reproduced the gate result. Otherwise classify the missing proof explicitly as `PARTIAL`, `UNKNOWN`, or `BLOCKED`.

- [ ] **Step 8: Commit final verification evidence metadata**

```bash
git add tests/test_provenance_failure_matrix.py scripts/verify_nina_provenance.py .github/workflows/e2e.yml
git commit -m "test: close nina provenance failure matrix"
```

## Final evidence gate

Do not label the feature `VERIFIED` until the following exact chain exists:

`commit → CI run → tests → runtime execution → evidence artifact → artifact digest → standalone IGOR verifier → replay → final gate result`

The existing OLA Run #68 evidence remains a baseline proof and is not reused as proof of the new NINA product contract.
