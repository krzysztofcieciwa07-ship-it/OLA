# OLA di-OS OCI Release Chain

## Purpose

Build one OCI image from one exact Git commit, publish it to GHCR, test the **published image by digest**, create a GitHub artifact attestation for that same registry digest, and independently verify the attestation before the digest can be considered a staging candidate.

This workflow does not deploy to Railway or approve production. Its evidence manifest deliberately ends with `deployment=NOT_TRIGGERED` and `human_gate=PENDING`.

## Trigger and permission model

- Pull requests targeting `main`: run policy tests, release-gate policy tests, and build `linux/amd64` without publishing.
- Pushes to `main`: validate first, then enter the publisher job.
- Pushes to the fixed release-candidate branch `security/oci-release-chain-20261112`: the publisher may run only when `github.actor` is the repository owner account `krzysztofcieciwa07-ship-it`; it still requires all exact-source gates to pass.
- Manual dispatch on `main`: same publisher policy; every required exact-source gate must already be successful.
- Manual dispatch on any other branch: validate/build only; no registry publication.

The PR validation job has only `contents:read`. The separate publisher receives `actions:read`, `packages:write`, `attestations:write`, and `id-token:write`, and its source-branch condition is restricted to `main` or the fixed owner-controlled release-candidate branch. The publisher waits for the full exact-source evidence set used by Final Production Gate, including the nested independent Ollama IGOR job and the Frontier Baseline reference. Missing or pending gates are polled for at most 30 minutes; a failed gate or timeout blocks publication.

The workflow checks out and asserts the exact event SHA before building. It passes that SHA into `OLA_SOURCE_COMMIT` and the OCI revision label.

## Published-image verification sequence

After publishing, the workflow pulls the exact `image@sha256:...` reference and:

1. Checks the OCI revision label against the expected source commit.
2. Checks `/app/ola-build-info.json` inside the pulled image against the same commit.
3. Runs `tests/test_core_readiness.py` inside that exact image.
4. Runs Trivy against that exact published digest; CRITICAL and HIGH vulnerabilities with `ignore-unfixed=true` block the release.
5. Only after those checks pass, creates and verifies the attestation.

The `sha-<commit>` tag is a convenience locator only. It is not the artifact identity and may be moved. The immutable identity used in all evidence and deployment hand-offs is the registry manifest digest.

## Cryptographic policy

The published image digest is the subject of the attestation. Verification requires:

- exact GHCR image name and full lowercase `sha256` digest;
- GitHub OIDC issuer;
- exact repository and signer workflow `.github/workflows/ola-oci-release.yml`;
- source ref `refs/heads/main`;
- exact full 40-character source commit SHA, checked against the certificate's source repository digest;
- SLSA provenance v1 statement whose subject contains the exact image name and digest;
- GitHub-hosted runner (self-hosted runners are denied).

The workflow also runs three negative controls against the published image: changed digest, changed source commit, and changed signer-workflow identity. Each must exit non-zero. The unmodified image must verify first; otherwise negative tests are not counted.

## Registry access and Railway prerequisite

GHCR packages are private by default. This workflow intentionally does **not** make the package public. Railway private-registry pulls require a compatible Railway plan and a GitHub Personal Access Token with `read:packages`, configured in the Railway service's registry credentials. Never commit this token or print it in workflow logs.

Making the package public is a separate owner decision and is not automated here.

The Railway connector used for this project cannot attach credentials to a private image source. Therefore, the first switch to a private GHCR digest must be configured in the Railway dashboard after the account plan and credential prerequisites are confirmed. Do not stage or accept a deployment until image pull access is in place.

**Merge safety:** the current staging API and Worker source the repository's `main` branch through Railpack. Merging this PR to `main` can trigger an independent Railway staging deployment. The fixed owner-controlled candidate branch is used to obtain the first GHCR digest and attestation without merging to `main`. Do not merge until that auto-deploy path has been deliberately controlled or a staging deployment is explicitly authorized.

## Deployment hand-off

After a successful release workflow, the evidence artifact contains:

- source repository, ref and commit SHA;
- GHCR image name and exact digest;
- immutable image reference (`image@sha256:...`);
- required CI gate verification;
- published-image source-label/build-info verification;
- in-image readiness test result and exact-digest Trivy result;
- positive attestation verification and three negative-test outcomes;
- `deployment=NOT_TRIGGERED` and `human_gate=PENDING`.

The next separate stage is to configure the staging API and Worker to use the same approved digest. Staging must pass fresh readiness and worker checks plus a 60-minute stability window before production is considered.

No Railway deployment, Railway configuration change, public package visibility change, or Human Gate approval is performed by this workflow.
