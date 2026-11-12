# OLA OCI Release Chain Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one immutable OCI image from an exact OLA source commit, attest the registry image digest, and prove both successful verification and fail-closed rejection before any Railway deployment is considered.

**Architecture:** GitHub Actions builds and publishes the Docker image to GHCR only for `main`; PRs build without publishing. GitHub artifact attestations bind the OCI image name and digest to the exact source commit and signer workflow. A small standard-library verifier invokes GitHub CLI and then independently checks the returned SLSA statement's subject. Railway deployment remains a separate, human-authorized stage.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, `actions/attest`, GitHub CLI attestations, Python 3.13 standard library, `unittest`, Railway.

## Global Constraints

- Feature Freeze: only release/supply-chain work is in scope.
- No Railway service is changed or deployed by this release workflow.
- No GHCR package is made public automatically.
- The image is identified by `image@sha256:...`, not by a mutable tag.
- Verification must bind repository, signer workflow, branch ref, exact source commit and exact OCI digest.
- Any missing evidence or failed verification must return non-zero.
- Negative controls must reject a changed digest, changed source commit and changed signer workflow.
- Human Gate remains pending until a separate operator decision.

---

### Task 1: Add the OCI attestation policy verifier

**Files:**
- Create: `scripts/verify_oci_attestation.py`
- Create: `tests/test_oci_attestation.py`

**Interfaces:**
- Consumes: `image`, `digest`, `repository`, `signer_workflow`, `source_ref`, `source_sha`.
- Produces: `verify_oci_attestation(...) -> dict` with `status=VERIFIED`, or raises `ValueError` / `VerificationError`.

- [x] Add focused tests for exact image+digest acceptance, signer/source flags, wrong SLSA predicate, wrong subject digest, GitHub CLI failure, mutable tags, malformed digest and malformed source SHA.
- [x] Observe the behavior tests fail against the empty verifier stub.
- [x] Regression: observed failure for `sha1:`-prefixed source digest; changed policy to the exact raw source commit SHA.
- [x] Implement strict input validation, `gh attestation verify` invocation and exact statement-subject enforcement.
- [x] Run the focused tests and confirm all pass.

Command: `python -m unittest discover -s tests -p 'test_oci_attestation.py' -v`

Expected: 7 tests pass; invalid inputs fail before invoking GitHub CLI; all external verification failures fail closed.

### Task 2: Add the GitHub OCI release workflow

**Files:**
- Create: `.github/workflows/ola-oci-release.yml`

**Interfaces:**
- Consumes: exact `github.sha`, Dockerfile build context, `GITHUB_TOKEN` with `packages:write`, OIDC identity.
- Produces: GHCR immutable digest, GitHub provenance attestation, and a release evidence artifact.

- [ ] PR: run policy tests and build `linux/amd64` without registry push.
- [ ] Main push/manual dispatch on `main`: login to GHCR, build and push with exact source SHA label, attest the `build-push-action` digest, and verify it using the exact repository/workflow/ref/commit constraints.
- [ ] Run negative controls for wrong digest, source commit and signer workflow; each must fail after the positive verification has passed.
- [ ] Publish a manifest with `deployment=NOT_TRIGGERED` and `human_gate=PENDING`.

Expected: PR jobs never publish; only a main release run can publish and attest; no Railway deployment step exists in this workflow.

### Task 3: Document registry and deployment hand-off

**Files:**
- Create: `docs/OCI_RELEASE_CHAIN.md`
- Create: `docs/plans/2026-11-12-oci-release-chain.md`

- [ ] Document the evidence chain and exact trigger behavior.
- [ ] Document GHCR private-by-default behavior and the Railway Pro + `read:packages` credential prerequisite.
- [ ] Explicitly leave package-public visibility and all Railway deployment changes outside automatic execution.

Expected: an operator can identify the exact release digest and prerequisites without guessing or copying a mutable tag.

## Unresolved external prerequisites

- Confirm Railway workspace plan supports private registry pulls (Pro or higher).
- The owner must configure a GitHub `read:packages` token in Railway's dashboard; the token must never be committed or exposed to CI logs.
- The first Railway source switch to a private image cannot be done by the connected Railway tool because it does not accept private-registry credentials. It must be configured in the dashboard or through a separately authorized Railway API workflow.
- The actual deploy-by-digest behavior, running deployment metadata binding, fresh `/readyz` and 60-minute stability window remain NOT VERIFIED until tested against Railway staging.