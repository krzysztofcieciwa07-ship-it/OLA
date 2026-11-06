# TRACEFORGE v0 — Reproducible Knowledge Proof

This slice proves one narrow contract before any pattern/mechanism/product layer is added:

`TRACE -> SOURCE -> ARTIFACT -> EVIDENCE -> VERIFY -> GRAPH -> REPLAY -> RECOVER`

## What is real in v0

- Search DNA capture (`query`, route, source, timestamp, failed/successful routes, recovery path).
- SHA-256 evidence for acquired artifacts.
- Independent re-verification against the source bytes.
- Explicit graph nodes and provenance edges.
- Append-only hash-chained event log with replay verification.
- Fail-closed recovery from the recorded provenance route.
- Tamper rejection when an artifact or source no longer matches the recorded digest.
- Exported `knowledge_package/manifest.json`, `graph.json`, and `events.jsonl`.

## What is deliberately not claimed

Pattern Discovery, Mechanism Discovery, Reuse Scoring, monetization, remote/web acquisition, signatures, and Evidence Graph integration are not part of this proof. They remain UNVERIFIED until added behind tests.

## Run

```bash
PYTHONPATH=. pytest -q tests/test_traceforge_v0.py
printf 'reproducible knowledge\n' > /tmp/traceforge-source.txt
PYTHONPATH=. python scripts/run_traceforge_v0.py \
  --source /tmp/traceforge-source.txt \
  --root /tmp/traceforge-proof \
  --query 'find canonical source' \
  --exercise-recovery
```

The command exits non-zero on verify, replay, or recovery failure. A successful run emits JSON with `final_status: VERIFIED` and writes the knowledge package under the selected root.
