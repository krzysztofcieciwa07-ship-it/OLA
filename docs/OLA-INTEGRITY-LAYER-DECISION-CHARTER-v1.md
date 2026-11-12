# OLA Integrity Layer — Decision Charter v1.0

**Status:** Active product-scope decision  
**Decision window:** First 60 days from adoption  
**Purpose:** Protect the team from building capabilities that the market has not validated.

## 1. North Star

> OLA Integrity Layer shortens the path from a code change to an audit-usable evidence record.

The product translates technical software-supply-chain and ICT change-management artefacts into an Evidence Manifest that an auditor can inspect and independently verify.

## 2. The wedge

- **One problem:** technical artefacts are not automatically mapped into usable DORA ICT change-management evidence.
- **One customer:** a regulated financial entity in scope of DORA.
- **One process:** ICT Change Management.
- **One product output:** the Evidence Manifest.

The initial buyer/problem owner/user/recipient may differ: economic buyer (CTO/CISO), problem owner (ICT Risk/Compliance), technical user (DevSecOps/Engineering), recipient (auditor). Discovery must identify the real budget owner rather than assume the persona.

## 3. Critical hypotheses — Kill Assumptions

| ID | Hypothesis | Evidence required | Validation method |
|---|---|---|---|
| H1 | An external auditor can understand and judge the Evidence Manifest without the builder explaining it. | Recorded auditor feedback on a real, redacted sample; explicit missing evidence and acceptance limits. | Walk-through with independent auditor; record what is understood, rejected or requested. |
| H2 | Manual DORA evidence collection is sufficiently costly and painful. | Baseline elapsed time, staff roles, handoffs, rework and cost for a real change/sample period. | Interview the organisation and time the current process; compare like-for-like. |
| H3 | A budget owner will pay for the outcome. | Priced paid-pilot proposal with named budget owner, scope and decision date; strongest evidence is signed order/contract or payment. | Present a priced pilot; distinguish interest, intent, procurement progress and actual payment. |
| H4 | SHA-bound evidence is valued beyond a readable report. | Buyer/auditor can identify a concrete decision or risk improved by exact source/artifact binding. | Compare a plain report with a source-bound manifest; ask what they would pay to retain or verify. |

Each hypothesis is classified only as \`VALIDATED\`, \`FALSIFIED\` or \`UNKNOWN\`, with date, source, evidence reference, confidence and owner. Positive comments and GitHub stars do not validate willingness to pay.

## 4. One deliverable

The Evidence Manifest is the product artefact. It must show, for one ICT change:
- regulatory/control reference and the limits of the mapping;
- control outcome (\`PASS\`, \`FAIL\`, \`PARTIAL\`, \`BLOCKED\`, \`UNKNOWN\`, \`SKIPPED\`, \`NOT_APPLICABLE\`);
- evidence integrity (\`VERIFIED\`, \`INVALID\`, \`UNVERIFIED\`);
- human approval (\`APPROVED\`, \`PENDING\`, \`REJECTED\`);
- evidence references, authoritative source identity and capture time;
- exact tenant, repository, change ID, full source commit SHA and released-artifact digest;
- missing evidence, exceptions, verifier result and limitations;
- a clear \`READY\` / \`NOT_READY\` summary that cannot disguise a non-pass state.

\`SKIPPED != PASS\`. \`NOT_APPLICABLE != PASS\`. \`UNKNOWN\` is never promoted. A digest proves byte consistency, not truth of the source, the independence of a role or compliance with law. The pack is not a certification or legal opinion.

## 5. What we deliberately do not build for 60 days

- No Knowledge Graph or graph database.
- No dashboard.
- No AI Auditor.
- No NIS2, ISO 27001 or SOC 2 packs.
- No marketplace.
- No multi-tenant platform.

Collectors, adapters, runtime, CI workflows and agents are implementation means only. Build or modify them only where they unblock production of the Evidence Manifest or directly test H1–H4.

## 6. Decision filter for every proposed task

A task is admitted to MVP only if its proposal states:
1. Which of H1, H2, H3 or H4 it tests.
2. The observable result that would validate or falsify that hypothesis.
3. Why the task cannot be completed manually for the pilot.
4. The smallest implementation that produces the required evidence.
5. The stop condition if the hypothesis is falsified.

Otherwise, place it in the strategic backlog. No exception for technically interesting work.

## 7. 30-day MVP success

At day 30, success means:
1. one working DORA Evidence Manifest for one real change on one repository;
2. one end-to-end demonstration from change request and approval through PR, identity, tests, commit, released artefact and post-deployment verification;
3. H1–H4 each classified as validated, falsified or unknown using evidence from at least five customer/auditor conversations and a priced-pilot discussion.

Code volume, number of modules, dashboard views, downloads or stars are not success criteria.

## 8. Commercial validation sequence

\`INTEREST\` → \`TECHNICAL VALIDATION\` → \`OPERATIONAL VALIDATION\` → \`PROOF OF VALUE\` → \`PRICED PILOT\` → \`PAYMENT\` → \`RENEWAL\`.

Do not equate a demonstration request, positive feedback, pilot intent, auditor comprehension, a signed pilot or recurring revenue. Track them separately.

## 9. Guardrails

- Start with DORA ICT change management only. Other regimes wait until after the first paid pilot.
- A successful local validator means only that the supplied bundle satisfies the pack contract.
- No claim of full DORA compliance or auditor acceptance without independent, documented evidence.
- Do not merge product work to \`main\` while required checks are pending or failing.
- Do not promote to Railway or claim production completion on the basis of GitHub CI alone.
- Every public pack release must be versioned, source-bound and have independently verifiable build provenance.

## 10. Review trigger

Review this charter after 30 days or earlier if any of H1–H4 is falsified. Change the strategy based on evidence, not enthusiasm or sunk engineering cost.
