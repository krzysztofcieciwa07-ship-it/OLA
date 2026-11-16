## Summary

<!-- What changed and why? -->

## Strategic admission — OLA Integrity Layer Decision Charter v1.0

- Hypothesis tested: `H1` / `H2` / `H3` / `H4` / `SECURITY-OR-RELIABILITY-MAINTENANCE` / `GOVERNANCE-DOCS-ONLY`
- Observable result that would validate or falsify it:
- Why this evidence cannot be obtained manually for the pilot:
- Smallest implementation that produces the evidence:
- Stop condition if the hypothesis is falsified:
- 60-day non-goals affected (Knowledge Graph, dashboard, AI Auditor, other regulatory packs, marketplace, multi-tenant platform, new runtime/gateway, broad adapters): `NONE` or explicit justification:

Product work without a direct, observable contribution to H1-H4 belongs in the strategic backlog, not the MVP.

## Scope and risk

- [ ] Runtime behavior
- [ ] Security or trust boundary
- [ ] Tenant isolation or persistence
- [ ] CI/CD or release process
- [ ] Product Evidence Manifest / DORA pack
- [ ] Documentation or governance only

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
- [ ] `SKIPPED` and `NOT_APPLICABLE` are never reported as `PASS`.
- [ ] Documentation does not overstate implementation or production readiness.
- [ ] No change is promoted to production based on GitHub CI alone.

## Rollback

<!-- How can this be safely reverted? -->