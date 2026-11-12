# OLA di-OS OCI Release Chain

## Purpose

Build one OCI image from one immutable Git commit, publish it to GHCR, create a GitHub artifact attestation for the **registry image digest**, and independently verify the attestation before that digest can be considered a staging candidate.

This workflow does not deploy to Railway and does not approve production. Its manifest deliberately ends with `deployment=NOT_TRIGGERED` and `human_gate=PENDING`.

## Trigger behavior

- Pull requests targeting `main`: run the focused policy tests and build the Docker image without publishing it.
- Pushes to `main`: build and publish `ghcr.io/krzysztofcieciwa07-ship-it/ola-di-os:sha-<commit>`.
- Manual dispatch on `main`: same publish and attest path.
- Manual dispatch on any other branch: build only; no registry publication or attestation.

The workflow checks out and verifies the exact PR head SHA or event SHA before building. It passes that SHA into `OLA_SOURCE_COMMIT` and the OCI revision label.

## Cryptographic policy

The published image digest is the subject of the attestation. Verification requires:

- GHCR image name and immutable `sha256` digest;
- GitHub OIDC issuer;
- exact repository and signer workflow `.github/workflows/ola-oci-release.yml`;
- source ref `refs/heads/main`;
- exact full 40-character source commit SHA, checked against the certificate's source repository digest;
- SLSA provenance v1 statement whose subject contains the exact image name and digest;
- GitHub-hosted runner (self-hosted runners are denied).

The workflow also runs three real negative controls against the published image: changed digest, changed source commit and changed signer-workflow identity. Each must exit non-zero. The unmodified image must verify first; otherwise negative tests are not counted.

## Registry access and Railway prerequisite

GHCR packages are private by default. This workflow intentionally does **not** make the package public. Railway private-registry pulls require Railway Pro and a GitHub Personal Access Token with `read:packages`, configured in the Railway service's **Settings → Source → Registry Credentials → GitHub Access Token** field. Never commit this token or print it in workflow logs.

Making the package public is an irreversible visibility decision in GitHub Packages: public packages cannot later be switched back to private. That decision requires separate owner approval and is not automated here.

The Railway connector used for this project cannot attach credentials to a private image source. Therefore, the first switch to a private GHCR digest must be configured in the Railway dashboard after the Pro/credential prerequisite is confirmed. Do not stage or accept a deployment until the image pull access is in place.

## Deployment hand-off

After a successful release workflow, the evidence artifact contains:

- source repository, ref and commit SHA;
- GHCR image name and exact digest;
- immutable image reference (`image@sha256:...`);
- positive attestation verification result;
- three required negative-test outcomes;
- `deployment=NOT_TRIGGERED` and `human_gate=PENDING`.

The next separate stage is to configure the staging API and worker to use the same approved digest, then explicitly authorize the staging deployment. Staging must pass fresh readiness and worker checks plus a 60-minute stability window before production is considered.

No production deployment, Railway configuration change, public package visibility change or Human Gate approval is performed by this workflow.
