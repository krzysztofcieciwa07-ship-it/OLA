# OLA OCI Release Chain Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one OCI image from an exact source commit, require the complete exact-source evidence gate, test and scan the published image by digest, attest that digest, and prove fail-closed rejection before any Railway deployment is considered.

**Architecture:** GitHub Actions validates pull requests without registry permissions. The main publisher waits for the existing Final Production evidence set and the independent Ollama IGOR job, then pushes one image to GHCR, pulls the resulting digest, checks embedded source binding, runs readiness-contract tests and Trivy, and only then attests and verifies that digest. Railway remains a separate, human-authorized deployment stage.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, GitHub artifact attestations, GitHub CLI, Python 3.13 standard library, `unittest`, Trivy, Railway.

## Global Constraints

- Feature Freeze: only release/supply-chain work is in scope.
- No Railway service is changed or deployed by this workflow.
- No GHCR package is made public automatically.
- PR jobs never receive registry, attestation-write or OIDC-write permissions.
- The image identity is `image@sha256:...`; the `sha-<commit>` tag is only a convenience locator.
- The publisher requires all exact-source Final Production evidence gates, the independent Ollama IGOR job, and the Frontier Baseline reference to pass.
- The publisher must test and scan the **same digest** that receives the attestation.
- Any missing, pending, failed, source-mismatched or unavailable required evidence must block publication.
- Negative controls must reject a changed digest, changed source commit and changed signer workflow.
- Human Gate remains pending until a separate operator decision.
- Do not merge to `main` while Railway staging API/Worker are still configured to build automatically from `main`, unless the staging deployment path has been deliberately controlled.

---

### Task 1: Add the OCI attestation policy verifier

**Files:**
- Create: `scripts/verify_oci_attestation.py`
- Create: `tests/test_oci_attestation.py`

**Interfaces:**
- Consumes: `image`, `digest`, `repository`, `signer_workflow`, `source_ref`, `source_sha`.
- Produces: `verify_oci_attestation(...) -> dict` with `status=VERIFIED`, or raises `ValueError` / `VerificationError`.

- [x] Add focused tests for exact image+digest acceptance, signer/source flags, wrong SLSA predicate, wrong subject digest, GitHub CLI failure, mutable tags, malformed digest and malformed source SHA.
- [x] Implement strict input validation, `gh attestation verify` invocation and exact statement-subject enforcement.
- [x] Run the focused tests and confirm all 7 pass.
- [x] Correct the source-digest input to the raw full Git SHA expected by GitHub certificate verification.
- [x] Correct and verify the GHCR name regex.

Command: `python -m unittest discover -s tests -p 'test_oci_attestation.py' -v`

### Task 2: Add the OCI release workflow and exact-source release gate

**Files:**
- Create/modify: `.github/workflows/ola-oci-release.yml`
- Create: `scripts/verify_release_gates.py`
- Create: `tests/test_release_gates.py`

**Interfaces:**
- `evaluate_release_gates(expected_sha, exact_runs, reference_runs, igor_jobs) -> dict`
- `verify_release_gates(repository, expected_sha, token, timeout_seconds, poll_seconds) -> dict`
- Required CI gate state: `VERIFIED`, `PENDING`, or `BLOCKED`.

- [x] Keep PR validation to `contents:read`; PR builds must not push to GHCR.
- [x] Isolate registry and OIDC write permissions to the publisher job.
- [x] Add the exact-source evidence poll based on the Final Production Gate's required workflow list.
- [x] Require the nested `igor-independent-ollama / igor-ollama` job to succeed; a skipped OpenAI-only job is not a substitute.
- [x] Fail closed on missing, pending, source-mismatched, failed or timed-out evidence.
- [x] Add unit tests for verified, missing, pending, failed, wrong SHA, missing/failed IGOR and newest-run selection; 9 local tests pass.
- [ ] Confirm the full PR CI run passes for the new branch head.

### Task 3: Test and scan the published image by digest before attestation

**Files:**
- Modify: `.github/workflows/ola-oci-release.yml`

- [x] Pull the registry image using the exact `image@sha256:...` reference.
- [x] Verify `org.opencontainers.image.revision` and `/app/ola-build-info.json` both equal the source SHA.
- [x] Run `tests/test_core_readiness.py` inside the pulled image.
- [x] Run Trivy against the exact published digest with CRITICAL/HIGH blocking.
- [x] Place attestation creation and positive/negative verification after image checks.
- [ ] Confirm PR CI accepts the updated workflow syntax and all security checks.
- [ ] On a controlled main release, confirm real GHCR push, digest pull, exact-image tests, Trivy and attestation verify all pass.

### Task 4: Document registry and deployment hand-off

**Files:**
- Modify: `docs/OCI_RELEASE_CHAIN.md`
- Modify: `docs/plans/2026-11-12-oci-release-chain.md`

- [x] Document exact-source gate enforcement and polling timeout.
- [x] Document image source-binding tests and digest-scoped Trivy.
- [x] Distinguish mutable convenience tags from immutable OCI digests.
- [x] Document private GHCR and Railway credential prerequisites.
- [x] Document the staging auto-deploy merge hazard.
- [ ] Confirm Railway plan and private-registry credential setup before a staging image switch.

## Deployment hand-off

- The publisher job produces no Railway deployment.
- The release manifest must state `deployment=NOT_TRIGGERED` and `human_gate=PENDING`.
- A separate operator action must configure staging API and Worker to the same approved digest.
- Staging must show exact image binding, fresh API readiness, actual Worker activity and 60-minute stability before a production change is considered.

## Unresolved external prerequisites

- Confirm the Railway workspace plan supports private registry pulls.
- Configure a GitHub token with `read:packages` in Railway's dashboard; it must never enter Git or CI logs.
- The current Railway connector cannot attach private-registry credentials to a service. The first private-image source switch must use the dashboard or a separately authorized workflow.
- The staging API and Worker currently follow `main` via Railpack; control that trigger before merging this PR.
- Production Worker creation, deploy-by-digest, independent runtime verification, fresh `/readyz`, 60-minute stability and Human Gate remain NOT VERIFIED.
