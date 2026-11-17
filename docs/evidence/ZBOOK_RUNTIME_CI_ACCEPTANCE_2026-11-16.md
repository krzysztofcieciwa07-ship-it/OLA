# ZBook Local Runtime — CI Acceptance Record

Date: 2026-11-16
Scope: isolated local worker runtime and provider/provenance test suite
Repository: krzysztofcieciwa07-ship-it/OLA
Branch: spec/zbook-local-agent-runtime-20261110
Verified commit: 8e33071252e01b486b45849c358dae6500c1c1d9
Pull request: #205 (kept Draft; panel integration is pending)

## Acceptance result

**READY — CI/runtime implementation scope only.**

At the verified commit, all 22 GitHub Actions workflow runs completed successfully:
- isolated Docker worker runtime;
- real Ollama runtime gate;
- NINA → Ollama → IGOR full-flow gate;
- Python package CI and E2E;
- CodeQL;
- supply-chain evidence;
- provenance and mutation gates;
- product gate;
- final production evidence gate.

The isolated-worker job ran the focused pytest set successfully (66 tests), built the worker image from a digest-pinned Python base, and verified the worker image by immutable image ID. The worker dependency pin was updated to cryptography 50.0.2.

The NINA/IGOR test used Ollama model qwen2.5:0.5b-instruct and independently verified the expected result 391, provenance and replay evidence. Its six agent profiles were executed in-process. This is **not** evidence of six separate isolated agent containers.

## Explicitly not accepted / pending

- Windows/ZBook host execution: UNKNOWN (not run on the user's device).
- Final PowerShell launcher and one-command operator experience: pending.
- OLA Panel Sterowania API/event integration: pending frontend and API contract reconciliation.
- End-to-end panel → backend → local ZBook executor → evidence return: not verified.
- Production deployment or merge to main: not performed.

## Operating decision

Keep PR #205 in Draft until the frontend/panel contract is available and the complete round trip is tested. Do not weaken worker isolation, provenance requirements, or secret handling to bypass integration failures.

## Evidence

- Commit: https://github.com/krzysztofcieciwa07-ship-it/OLA/commit/8e33071252e01b486b45849c358dae6500c1c1d9
- PR: https://github.com/krzysztofcieciwa07-ship-it/OLA/pull/205
- Final Production Gate: https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/43932757783
- NINA/IGOR Ollama flow: https://github.com/krzysztofcieciwa07-ship-it/OLA/actions/runs/43932758301
