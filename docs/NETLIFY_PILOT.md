# Netlify pilot — OLA di-OS NINA API

Status: isolated, non-production experiment. The Netlify site is a static test console; Railway remains the FastAPI host.

## Purpose

Verify Netlify static hosting and a narrow same-origin proxy to the existing Railway staging API. The test console checks:

1. `GET /api/health` — liveness only.
2. `GET /api/readyz` — local core readiness only; `system_acceptance=NOT_VERIFIED` is expected and is not production acceptance.
3. Unauthenticated `POST /api/nina-run` — must return HTTP 401.
4. Authenticated unknown capability `shell` — must return the NINA policy-block shape (`nina.status=BLOCK`, `provenance.status=NOT_CREATED`, empty replay and no run ID) before runtime or evidence writes.
5. Authenticated `POST /api/nina-run` with `safe_expression` — NINA and IGOR must verify the run, provenance and replay must verify, and Human Gate must remain `BLOCK/REVIEW`.

The authenticated test run appends events to the tenant's staging evidence chain. Use only a newly provisioned, empty synthetic staging tenant and its dedicated API key. Never use a production key, customer key, shared owner key, or a tenant that already contains evidence. The replay check expects the initial nine-event execution chain.

## Architecture

- Frontend: Netlify static publish directory `netlify-pilot/`.
- API origin: `https://ola-fastapi-api-staging.up.railway.app`.
- Proxy: three explicit `200` rewrites in `netlify.toml`:
  - `/api/health` → `/health`
  - `/api/readyz` → `/readyz`
  - `/api/nina-run` → `/nina-run`
- No wildcard `/api/*` route, no production API route, no `/chat`, checkout, Stripe, workflow, or approval endpoint.
- The browser sends the dedicated staging key as `X-API-Key` over HTTPS, then clears the input. The page does not use localStorage or sessionStorage and does not print the key.
- The key traverses the Netlify proxy and Railway staging API. Use a dedicated, low-privilege test key that can be rotated; never send a production/owner/customer key through this pilot.
- The proxy is same-origin from the browser's perspective; the page does not need permissive CORS.
- Netlify proxy rewrites have a 26-second timeout. The functional test uses a bounded deterministic capability, not long-running LLM chat or workflow execution.

## Safety boundary

- Pilot branch: `pilot/netlify-nina-api-20261110`.
- Production branch remains `main`.
- The build script passes only for the named pilot branch in `branch-deploy` or `deploy-preview` context.
- Production and unknown build contexts fail closed.
- Netlify has no API keys, database credentials, LLM credentials, or Stripe credentials in build variables or published assets.
- The proxy destination is hardcoded and checked against the single staging host above.
- Published files are restricted to a strict allowlist and scanned for common secret patterns.
- `noindex` is not access control. The branch URL is public to anyone who knows it unless separate Netlify access protection is configured. Do not share the URL widely, and do not put anything except the dedicated staging key into the tester.

## Netlify setup

1. Create a separate Netlify site and connect only `krzysztofcieciwa07-ship-it/OLA` through the GitHub App. Grant access to this repository only.
2. Keep the production branch as `main`; do not set the pilot branch as production.
3. Enable only `pilot/netlify-nina-api-20261110` as an individual branch deploy.
4. Leave the base directory empty. Let Netlify read the repository's `netlify.toml`.
5. Do not add environment variables, credentials, custom domains, or deploy hooks.
6. Trigger the branch deploy and wait for `NETLIFY_NINA_API_PILOT_BUILD_PASS`.
7. Open the branch URL and verify health/readiness/auth checks. For the authenticated test, enter a dedicated key for a newly created, empty synthetic staging tenant in the page itself; never paste it into ChatGPT.

## Acceptance criteria

- Build succeeds only in the allowed pilot branch and non-production context.
- Build proof confirms the exact branch, the three staging-only proxy routes, and no secret material in published assets.
- CI tests cover valid branch deploy, valid deploy preview, blocked main/production, blocked altered API origin, blocked wildcard proxy, blocked secret-like asset content, and missing Netlify context.
- Browser checks pass: health 200, readyz 200 with `core_status=READY`, and unauthenticated `/nina-run` 401.
- Unknown capability is blocked before execution and evidence creation.
- Authenticated NINA run: HTTP 200; NINA=VERIFIED; IGOR=VERIFIED; provenance=VERIFIED; replay=VERIFIED; Human Gate=BLOCK; final decision=REVIEW.
- The final `REVIEW` is intentional and correct: runtime verification is not human approval and is not deployment authorization.
- Main branch, Vercel, Railway production, Supabase, Stripe, and customer data remain unchanged.

## What this pilot proves — and does not prove

A green result proves a specific deterministic NINA request can traverse Netlify's proxy to Railway staging and return verifiable NINA/IGOR evidence with a fail-closed human gate. It does not prove real LLM execution, long-running workflows, chat, customer checkout, production acceptance, or commercial readiness. It also does not change the live OLA deployment.
