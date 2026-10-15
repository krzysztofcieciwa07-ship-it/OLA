# Windows preview bootstrap — bounded correction

This change repairs the new-preview path only. It does not migrate an existing
preview, alter Human Gate, authenticate the publisher, or authorize production.

## Source and branch

`workstation/OLA-Preview-Auth.ps1` still requires an exact 40-hex `ExpectedSha`, a
clean Git checkout, and a matching branch. The default branch remains
`ui/ola-command-center-live-20261014`. A different reviewed branch must be named
explicitly with `-ExpectedBranch`; detached HEAD and an empty branch are refused.

For a **new, absent** preview, after reviewing and committing the correction:

```powershell
& .\workstation\OLA-Preview-Auth.ps1 -CreatePreview `
  -ExpectedSha '<reviewed-full-source-sha>' `
  -ExpectedBranch '<reviewed-branch-name>' `
  -Model '<already-installed-local-ollama-model>'
```

Use the reviewed SHA containing the correction. An uncommitted working patch
intentionally fails the clean-checkout check. An existing container or data volume
still blocks creation. The ordinary invocation remains read-only; `-IssueKey` is
still a separate explicit operation on an already-configured preview.

## Build ordering and source checks

The script resolves a local application from `py.exe -3`, `python.exe`, or
`python3.exe`, probing for Python 3.10+. It does not run a supplied shell command,
download Python, install packages, or pull an Ollama model.

Before creating a pepper file or Docker data volume it now:

1. Runs the existing `scripts/build_source_manifest.py` generator.
2. Rechecks Git SHA, expected branch and checkout cleanliness.
3. Checks the generated inventory schema, source SHA and nonempty file inventory.
4. Builds the image. Its Dockerfile independently checks app/policies bytes against
   the generated inventory inside the build.
5. Rechecks Git SHA/branch/cleanliness and verifies that the inventory hash did not
   change during the build, then checks container/volume absence again.

A failed generator or image build therefore creates no new pepper file or data
volume. An old orphaned secret is deliberately not deleted or reused silently.
Failures after provisioning begins still preserve artifacts for manual diagnosis.
An existing inventory path with the reparse-point attribute, or a directory at
that path, blocks before the generator can write; the same check guards inventory
reads after generation/build. Missing files are allowed before generation, while
unexpected read/access errors block. This does not eliminate concurrent path swaps.

These are local consistency checks. They do not make source observation atomic,
defeat a privileged change-and-restore attack, attest a builder or process memory,
or prove a production deployment. The image inventory remains unsigned.

## PowerShell harness

```powershell
powershell -NoProfile -File .\tests\test_preview_bootstrap.ps1
```

The harness parses the actual script, loads its function definitions and replaces
external Git/Docker/Python/HTTP calls and secret generation with inert fixtures.
It covers a clean checkout without an inventory, an explicitly expected review
branch, rejected source/branch/dirty states, generator/schema/SHA failures, image
build failure, source/inventory changes, existing or newly appeared preview/data
volumes, and unavailable Python.

It never executes the product, builds an actual image, contacts a model, or creates
an actual credential. Running the same harness using portable `pwsh` on Linux is
PowerShell control-flow validation, **not Windows installation or product E2E**.
Actual Windows/ZBook startup, local model inference, operator onboarding, cockpit
flows and the independent review remain separate checks.
