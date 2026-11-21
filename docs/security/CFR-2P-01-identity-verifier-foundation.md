# CFR-2P-01 — OIDC Subject Verifier Foundation

## Scope

This candidate adds a bounded, fail-closed verifier for RS256 OIDC JWTs and returns a stable tuple-like identity (\`issuer\`, \`subject\`, tenant claim). It does **not** alter any approval endpoint or database record and is not wired into NINA, paid-order, or report-review flows.

## Verification contract

- Require explicit issuer, audience, JWKS URL, and exact HTTPS host allowlist.
- Reject HTTP, non-443 ports, userinfo, query/fragment, redirects, unsupported JWT algorithms, missing \`kid\`, oversized tokens/JWKS, ambiguous or non-RSA signing keys, and missing/invalid \`iss\`, \`aud\`, \`exp\`, \`iat\`, \`sub\`, or tenant claim.
- JWKS fetch has a 3-second timeout, no redirects, 64 KiB response cap, 32-key cap, and 5-minute cache. Unknown \`kid\` gets one bounded cache refresh.
- No token or claim values are logged.

## Integration remains a separate protected task

The verifier is not proof of tenant membership or authorization. Integration must bind a verified Subject ID to the tenant at author time, persist (\`issuer\`, \`subject\`) with the approval-relevant record, require verified reviewer identity, and enforce \`reviewer_subject != author_subject\` (and distinct report-review subject from both author and execution reviewer). Existing API-key IDs remain technical credentials, not human identity. Missing identity mapping must fail closed.

This candidate does not perform schema migrations, approvals, data writes, staging/production changes, or deployment. P0 remains BLOCKED until integration, isolated DB tests, independent review, and staging DB isolation are proven.
