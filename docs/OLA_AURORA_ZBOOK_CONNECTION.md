# OLA AURORA + API + Ollama: local ZBook connection (STAGING)

The isolated HTML preview has **no engine** by design. Do not open index.html
through file:// or a static HTTP server and claim OLA is running.

The real AURORA front end is served by FastAPI from the **same origin** as the
OLA API, at http://127.0.0.1:18081/ when a controlled local preview is started.

Existing (reused, not rebuilt): /health, /auth/session, /control/overview,
/chat, /nina-run, /evidence/{record_id}, NINA, IGOR, replay and policy gates.

## First connection — Windows 11 ZBook

Prerequisites: Git, Docker Desktop running, Ollama running, at least one
installed **local** chat-capable Ollama model (ollama list). A clean checkout
is mandatory. From the OLA repository in PowerShell:

~~~powershell
git fetch origin integration/aurora-api-engine-zbook-20261016
git switch --track -c integration/aurora-api-engine-zbook-20261016 origin/integration/aurora-api-engine-zbook-20261016
.\workstation\START-OLA-ZBOOK.ps1 -Setup -LiveTest
~~~

If the branch already exists locally, switch to it and use git pull --ff-only
instead of creating it again.

The launcher reuses existing OLA FastAPI, NINA, policy/evidence and Ollama, and
opens the live server page. For a missing preview, -Setup asks the existing
guarded helper to create one isolated container, volume and pepper, then issues
one tenant credential. It never destroys/replaces a container or database.
-LiveTest prompts for that credential and performs the real chat + evidence
round trip. Do not paste the key into Git, ChatGPT or a shared terminal log.

On subsequent runs, start with:

~~~powershell
.\workstation\START-OLA-ZBOOK.ps1 -LiveTest
~~~

If a previous preview exists but its source hash differs from the Git checkout,
the launcher will **BLOCK**, preserving existing data; investigate before an
authorized migration. The default without -Setup is read-only and never starts,
deletes or overwrites an existing service.

-IssueKey prints X_API_KEY_ONCE on the local terminal. Paste it into
AURORA > Ustawienia > X-API-Key > Zweryfikuj klucz. The verifier prompts for
the same key without storing it. Never share credentials in chat or Git.

A successful verifier run requires the six explicit checks:
API_HEALTH_OK, OLA_ROUTES_PRESENT, TENANT_AUTHENTICATED,
TENANT_CONTROL_CONNECTED, OLLAMA_RESPONSE_RECEIVED and
TENANT_EVIDENCE_READBACK_OK; status LOCAL_CHAT_API_ENGINE_CONNECTED.
Chat uses real Ollama, records a tenant-scoped digest and reads it back.
This is local connectivity proof only. It is NOT execution approval.

## Existing preview: preserve state

If the container ola-cc-preview already exists, **do not** run -CreatePreview.
Inspect instead:

~~~powershell
docker ps -a --filter name=ola-cc-preview
.\workstation\OLA-Preview-Auth.ps1
python .\scripts\verify_aurora_connection.py --health-only
~~~

-IssueKey refuses duplicate default tenant names. Recover the existing
credential from your own secure store. Do not remove volumes, rotate pepper,
or replace a live service to force the checks to pass.

## Diagnosis

- No /health: wrong port, stopped container or failed build. Inspect container
  status and docker logs ola-cc-preview (redact sensitive data).
- /health but missing routes: a static preview or wrong server, not OLA Core.
- HTTP 401: missing/incorrect tenant credential or pepper/database mismatch.
- Chat BLOCK: verify installed Ollama model and host Ollama on port 11434.
- Evidence digest mismatch: fail closed, do not mark VERIFIED.
- This installation exposes loopback only. Mobile access needs separately
  approved, authenticated network ingress — never expose it by 0.0.0.0.

## Limits

LOCAL_CHAT_API_ENGINE_CONNECTED checks the live chat model API and local
evidence readback. NINA task execution, independent IGOR, Human Gate, trusted
signing, external attestation and production deployment are NOT proven.
The staging GitHub branch and PR history are unsigned. Production remains
NO-GO pending owner-signed release and independent verification.
