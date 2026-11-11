# Contributing to OLA

OLA is an evidence-driven execution runtime. Changes must preserve the distinction between execution state, verification state, and evidence of what actually happened.

## Before changing code

1. Read the relevant sections of README.md, SECURITY.md, and docs/ENGINEERING_STANDARD.md.
2. Identify the exact behavior being changed and the security or tenant boundary it touches.
3. Keep changes narrow. Do not combine unrelated refactors with a bug fix.
4. Never commit API keys, signing keys, database files, customer data, or production evidence containing sensitive values.

## Local setup

Use Python 3.11 or newer:

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
~~~

On Windows PowerShell, activate with .venv/Scripts/Activate.ps1.

## Required local checks

Run the checks relevant to the change:

~~~bash
python -m pytest -q
python -m compileall -q app scripts tests
docker build -t ola:local .
~~~

The full test suite and Docker build are separate checks. Report each result independently. Do not claim a check passed unless it was actually executed against the candidate commit.

## Pull requests

- Use a focused branch and a descriptive Conventional Commit-style title.
- Explain the problem, the implementation, and any changed trust boundary.
- Include the exact commit SHA and links to CI runs.
- State any skipped, optional, failed, or unavailable checks explicitly.
- Preserve fail-closed behavior: unknown or unverifiable state must not become ALLOW or VERIFIED.
- Do not merge or deploy solely because documentation or a workflow definition exists.

## Evidence and release discipline

A successful unit test proves only the tested behavior. Production claims additionally require source-bound CI, runtime, integrity, provenance, human-approval, and deployment evidence as applicable. See SECURITY.md for release evidence expectations.
