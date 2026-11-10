# Netlify pilot — OLA di-OS NINA API

Status: isolated, non-production experiment. The Netlify site is a test frontend; Railway remains the FastAPI host.

## Purpose

Verify Netlify static hosting and a narrow same-origin proxy to the existing Railway staging API. The test console checks:

1. `GET /api/health` — liveness only.
2. `GET /api/readyz` — local core readiness only; `system_acceptance=NOT_VERIFIED` is expected.
3. Unauthenticated `POST /api/nina-run` — must return HTTP 401.
4. Authenticated `POST /api/nina-run` with `safe_expression` — NINA and IGOR must verify the run, provenance and replay must verify, and Human Gate must remain `BLOCK/REVIEW`.

The authenticated run appends evidence to the tenant's staging evidence chain. Use only a dedicated API key for a separate synthetic staging tenant. Never use a production key, a customer key, or a shared owner key.

## Architecture

- Frontend: Netlify static publish directory `netlify-pilot/`.
- API origin: `https://ola-fastapi-api-staging.up.railway.app`.
- Proxy: three explicit `200` rewrites in `netlify.toml`:
  - `/api/health` → `/health`
  - `/api/readyz` → `/readyz`
  - `/api/nina-run` → `/nina-run`
- No wildcard `/api/*` route, no production API route, no `/chat`, checkout, Stripe, workflow, or approval endpoint.
- The browser key is typed at run time, sent as `X-API-Key` over HTTPS, then cleared from the input. The page does not use localStorage or sessionStorage and does not print the key.
- The proxy is same-origin from the browser's perspective; no cross-origin credential sharing or CORS wildcard is required.
- Netlify's proxy rewrite timeout is 26 seconds. This pilot only runs the bounded deterministic `safe_expression` scenario; it is not a long-running LLM/chat gateway.

## Safety boundary

- Pilot branch: `pilot/netlify-nina-api-20261110`.
- Production branch remains `main`.
- The build script passes only for the named pilot branch in `branch-deploy` or `deploy-preview` context.
- Production and unknown build contexts fail closed.
- Netlify has no API keys, database credentials, LLM credentials, or Stripe credentials.
- The proxy destination is hardcoded and checked against the single staging host above.
- The published directory has an allowlist and a secret-pattern scan.
- No custom domain should be assigned. Keep the site unlisted/noindex.

## Netlify setup

1. Create a separate Netlify site and connect only `krzysztofcieciwa07-ship-it/OLA` through the GitHub App. Grant access to this repository only.
2. Keep the production branch as `main`; do not set the pilot branch as production.
3. Enable only `pilot/netlify-nina-api-20261110` as an individual branch deploy.
4. Leave the base directory empty. Let Netlify read the repository's `netlify.toml`.
5. Do not add environment variables, credentials, custom domains, or deploy hooks.
6. Trigger the branch deploy and wait for `NETLIFY_NINA_API_PILOT_BUILD_PASS`.
7. Open the branch URL and verify health/readiness/auth checks. For the authenticated run, use a dedicated staging API key for a synthetic tenant only.

## Acceptance criteria

- Build succeeds only in the allowed pilot branch and non-production context.
- Build proof confirms the exact branch, the three staging-only proxy routes, and no secret material in published assets.
- Browser checks pass: health 200, readyz 200 with `core_status=READY`, and unauthenticated `/nina-run` 401.
- Authenticated NINA run: HTTP 200; NINA=VERIFIED; IGOR=VERIFIED; provenance=VERIFIED; replay=VERIFIED; Human Gate=BLOCK; final decision=REVIEW.
- The final `REVIEW` is intentional and correct: a runtime verification is not Human Gate approval.
- Main branch, Vercel, Railway production, Supabase, Stripe, and customer data remain unchanged.

## What this pilot proves — and does not prove

A green result proves a specific deterministic NINA request can traverse Netlify's proxy to Railway staging and return verifiable NINA/IGOR evidence with a fail-closed human gate. It does not prove real LLM execution, long-running workflows, chat, customer checkout, production acceptance, or commercial readiness.
