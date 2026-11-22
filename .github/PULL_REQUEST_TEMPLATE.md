## Summary

<!-- What changed and why? -->

## GitHub Human Gate task

For any P0/P1/security/auth/identity/tenant/payment/production or other high-risk change, add exactly one line:

`Human Gate Task: #<existing issue number>`

The referenced Issue must exist, remain OPEN, and carry P0/P1/security or human-gate:required. Do not create a duplicate Issue. The GitHub policy check requires an independent write-enabled CODEOWNER approval on the exact current HEAD SHA, no author self-approval, and all review threads resolved. A push invalidates the prior approval. Missing governance token/permission evidence fails closed.

## Scope and risk

- [ ] Runtime behavior
- [ ] Security or trust boundary
- [ ] Tenant isolation or persistence
- [ ] CI/CD or release process
- [ ] Documentation only

Describe affected components and the failure mode this change addresses:

## Verification

| Check | Result | Exact run / evidence |
|---|---|---|
| Unit / contract tests | NOT RUN | |
| Integration / E2E | NOT RUN | |
| Security / provenance | NOT RUN | |
| Container build / runtime | NOT RUN | |

Candidate commit SHA:

## Safety review

- [ ] No secrets, credentials, or customer data added.
- [ ] Unknown states remain fail-closed.
- [ ] Evidence is bound to the candidate source SHA.
- [ ] Skipped and unavailable checks are disclosed.
- [ ] Documentation does not overstate implementation or production readiness.

## Rollback

<!-- How can this be safely reverted? -->