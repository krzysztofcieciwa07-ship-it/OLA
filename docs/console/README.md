# OLA task and evidence console

This replaces the existing `web/index.html` chat page in OLA. It is served by the
same FastAPI application at `/`; it is not a second backend or a Lovable deployment.
The change is based on integration PR #76, whose source-bound agent evidence is
required by the presentation checks. It must not be advertised as production-ready
until that integration's security, signature and deployment gates are satisfied.

## Behavior

- Existing tenant API keys are verified by `GET /console/session`. The response is
  tenant ID only and is not cached. No user, API key, or persistent login is created.
- The key stays in the current page's memory, is sent only in `X-API-Key` headers to
  fixed same-origin endpoints, and is cleared on disconnect/page exit. No storage,
  hardcoded password, remote endpoint configuration or external UI scripts.
- Key transmission requires HTTPS or loopback HTTP. Deployment must enforce TLS.
  This operator interface is not a public customer identity/onboarding system.
- User submission calls `/nina-run` once, then fetches that decision report's
  evidence IDs through the existing tenant-protected `/evidence/{id}` endpoint.
- A result is shown only after checking the requested task, tenant, run, six agent
  roles, common source/provider/model and codeact/final result agreement.
- IGOR and replay verdicts are explicitly backend reports. The browser checks
  consistency; it does not cryptographically authenticate a remote backend or
  declare a deployment trusted. Hashes are displayed for inspection.
- Deterministic execution is visibly distinguished from real LLM invocation.
  `REVIEW` stays pending. The console has no human-approval or payment action.
- Failed, timed-out or incomplete requests remain UNKNOWN and are not retried.
  A disconnected browser does not cancel work already accepted by the backend.
- Chat remains separate and never changes execution/evidence statuses. All server
  text is rendered through `textContent`; HTML from a task/model is not executed.
- JSON download is a scoped observation, not an attestation. Other-run replay
  metadata is excluded; the original decision report seal is removed because
  scoping changes that report. The backend remains the source of the original.

## Run and verify

Use the existing OLA deployment/installer, with its existing tenant API key and
configured model. `/` serves the console; no frontend build or npm installation
is needed. Both `OLA_SOURCE_COMMIT` and `OLA_RUNTIME_COMMIT` must refer to the
actual source used by the runtime. Do not invent a SHA to satisfy a green badge.
The current registered execution tools support bounded arithmetic/hash work;
this console does not add arbitrary business automation capabilities.

For isolated development proof, install `requirements.txt` and Node 20+:

```sh
python -m pytest -o addopts='' -q tests/test_console.py
node --test tests/web/console.test.mjs
python tests/web/prove_console.py > console-proof.json
```

The proof runner uses a temporary SQLite DB, an ephemeral tenant/key and the real
six-agent deterministic runtime. It passes the actual API response and fetched
records through the same JavaScript presentation model, then runs the standalone
Python verifier. It requires result 391, complete evidence, IGOR VERIFIED,
replay VERIFIED and terminal REVIEW. It does not call a paid provider, start
Ollama or approve a production release. Credentials are never printed.

The dedicated GitHub workflow repeats these checks and uploads the source-bound
observation. Node is required only for the console-specific tests, not the
production Python image or the ordinary Python regression suite.

The same workflow also installs Playwright 1.62.1 in a temporary directory and
runs `tests/web/prove_browser.py`. It starts a real loopback API with an isolated
temporary database and an ephemeral tenant credential supplied to Node through
stdin. Chromium exercises desktop (1440×1080) and mobile (390×844): failed login,
successful login, one real task submission, seven fetched evidence records,
result 391, backend IGOR/replay reports, terminal REVIEW, JSON download and logout.
The exported report is checked for source/run/tenant binding and credential
absence. Both runs are then checked by the standalone Python verifier. Screenshots,
a scoped JSON observation and credential-redacted diagnostic logs are uploaded.
This is deterministic browser/runtime proof, not real-model or deployment proof.

To run it outside CI, install Playwright and its Chromium browser, then set
`PLAYWRIGHT_MODULE_PATH` to the absolute `playwright/index.mjs` path and
`OLA_BROWSER_OUTPUT` to a directory outside the repository before running
`python tests/web/prove_browser.py`. The runner requires a POSIX host with local
socket support. No existing workstation database or tenant key is used.
