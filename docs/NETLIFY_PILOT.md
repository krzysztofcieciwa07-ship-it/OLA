# Netlify pilot — OLA di-OS

Status: isolated, non-production experiment.

## Purpose

Verify Netlify Git integration, branch-scoped build execution, static asset delivery, response security headers, and a machine-readable build proof. This pilot intentionally publishes only `netlify-pilot/`.

It does **not** deploy or proxy the OLA FastAPI backend, connect Supabase, configure Stripe, read customer data, or require any API credentials.

## Safety boundary

- Pilot branch: `pilot/netlify-static-20261110`.
- Production branch must remain `main`.
- The build script only passes on the named pilot branch in `branch-deploy` or `deploy-preview` context.
- Any `production` or unknown build context fails closed.
- No environment variables or secrets are required.
- No custom domain should be assigned.
- Do not merge this branch into `main` as a hosting migration.

## Netlify setup

1. Create a **new, separate Netlify site** and connect only `krzysztofcieciwa07-ship-it/OLA` through the GitHub App. Grant access to this repository only.
2. Keep the production branch as `main`; do not select the pilot branch as production.
3. In Project configuration → Developer settings → Continuous deployment → Branches and deploy contexts, enable only `pilot/netlify-static-20261110` as an individual branch deploy.
4. Leave the base directory empty. Let Netlify read `netlify.toml`; do not override the build command or publish directory in the UI.
5. Do not add environment variables, credentials, secrets, domains, redirects to production APIs, or databases.
6. Trigger the branch deploy. The build must report `NETLIFY_PILOT_BUILD_PASS`; then open the branch URL and run the browser checks.

The current branch build guard deliberately rejects `main`/production deploys. That expected failure is a protection control, not a production incident.

## Acceptance criteria

- Build succeeds only in the allowed branch context.
- `build-proof.json` reports `passed: true`, the exact pilot branch, and a non-production context.
- Browser checks pass for manifest, build proof, and security headers.
- No secrets or backend source files are present in the published directory.
- Main branch, existing Vercel project, Supabase project, and production services remain unchanged.

## What this test proves — and does not prove

A green result proves static hosting, branch isolation, and declared HTTP headers for this pilot. It does not prove that FastAPI, NINA, IGOR, Stripe, Supabase, worker processes, persistent storage, or the complete OLA product can run on Netlify.
