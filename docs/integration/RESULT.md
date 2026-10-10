# OLA integration checkpoint

Base: `5df5e5de1435ac088ce3a96365873807e2551911`.
Tested code commit: `14acee1ba1e4282c4cf8f973889eb55b987872e7`.
Local branch: `integration/all-ola-20261010`.
Classification: LOCAL INTEGRATION / PRODUCTION BLOCKED.

## Included scope

All 11 open PR heads observed in the recorded snapshot are ancestors of this integration: #37, #40, #58, #59, #60, #61, #64, #71, #73, #74, #75. Exact heads are recorded in `pr-snapshot-20261010.json`. #59 is included transitively through #60.

The consolidation includes CFR-18, Decision Fabric, evidence read APIs, TRACEFORGE, forensic source/nonce correlation, release health stability, watchdog controls, CodeQL SARIF enforcement, approval bypass protection, and Stripe session isolation.

Conflict resolutions retain the main branch's GPG signer authorization and fail-closed manifest validator. Payment results now require tenant authentication plus tenant/session/event/run correlation; public redirects do not expose tasks or results. CI selection rejects other sources/events and stale successful attempts. Duplicate push triggers were removed. Optional Jev availability no longer uses the forbidden secrets context in a job-level condition. TRACEFORGE is copied into the runtime image. Release reexecution receives the exact source identity and calls the standalone verifier; its scope is explicitly deterministic.

## Validation

- Full local suite: 232 passed, 4 GPG fixture setup errors, 1 dependency deprecation warning.
- GPG cause: the execution environment refuses the Unix socket required by gpg-agent (`Operation not permitted`). No replacement key or fabricated signature was introduced.
- Explicit subset excluding only `tests/test_signature_gpg.py`: 232 passed, 1 warning, 0 failed. This is not a full-suite PASS.
- All 28 workflow YAML documents parsed with duplicate-key rejection; embedded Python parsed; Bash steps were syntax checked (PowerShell steps excluded from Bash validation).
- `git diff --check` passed.
- Docker, actual Ollama inference, Windows workstation execution and remote CI for this integrated commit remain unverified here.

## Remaining branch coverage

65 non-main remote branches were inventoried: 34 included by ancestry, 4 producing no tree changes at the checkpoint, 23 with unresolved historical conflicts, and 4 with additional unintegrated deltas. See `branch-inventory-20261010.json`. The latter categories are NOT represented as merged. No historical branch or original PR was deleted or closed.

## Publication and production

The attempted push of this new integration branch was rejected by automatic approval review. Its stated reason was that publishing repository contents to GitHub lacked explicit authorization and might expose sensitive source code. The rejection was not bypassed. No draft integration PR was created, and no main merge or production promotion was performed in this operation.

Publication requires explicit permission to push this branch and create a draft PR. Production separately remains subject to authorized signer configuration (`OLA_ALLOWED_SIGNER_FPRS`), source signature verification, remote integration CI, independent evidence verification and the Human Gate. Local integration commits are unsigned.
