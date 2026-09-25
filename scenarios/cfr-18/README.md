# CFR-18 — Queue Resurrection

Forensic incident-lab scenario isolated under `scenarios/cfr-18/`.

## Status

**IMPLEMENTATION IN PROGRESS.** The forensic terminal state is not claimed until live execution proves the full chain: stack → fault → fix → assertions → stability → score → tamper detection → replay → bundle hash.

## Evidence rule

A valid SHA-256 chain provides tamper evidence, not external immutability or a digital signature. CFR-18 v1 does not claim Ed25519, Cosign, or external immutable storage.

## First verification gate

```bash
pytest -q scenarios/cfr-18/tests/test_evidence_vault.py
```

Then implement the remaining tasks in `docs/superpowers/plans/2026-09-25-cfr18-forensic.md` and execute the live verification procedure.
