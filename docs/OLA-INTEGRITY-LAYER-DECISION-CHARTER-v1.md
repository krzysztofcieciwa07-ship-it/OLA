# OLA Integrity Layer — Decision Charter v1.0

**Status:** ACTIVE PRODUCT SCOPE  
**Decision window:** First 60 days after adoption  
**Purpose:** Protect the team from building capabilities the market has not validated.

## 1. North Star

> OLA Integrity Layer shortens the path from a code change to an audit-ready evidence record.

We translate technical software-supply-chain and ICT change-management artefacts into one Evidence Manifest that an auditor or control owner can inspect and independently verify. We do not sell a new signing tool, a dashboard or a general-purpose compliance platform.

## 2. The wedge: one problem, one customer, one process

| Decision | MVP scope |
|---|---|
| Problem | Technical artefacts are not mapped consistently into usable evidence for DORA ICT change-management controls. |
| Customer | A regulated financial entity that is in scope of DORA. |
| Process | One software-related ICT change, from request and risk assessment through approval, implementation and post-implementation verification. |
| First product | OLA DORA Audit Evidence Pack — ICT Change Management. |
| Primary customer-facing output | One source-bound Evidence Manifest for one change. |

Buying and using roles are not interchangeable:

- Economic buyer: CTO or CISO — the actual budget owner must be identified, not assumed.
- Problem owner: Head of ICT Risk, Compliance or the equivalent control owner.
- Technical user: Head of DevSecOps, Engineering Manager or platform team.
- Evidence recipient: external auditor or independent control assessor.

The v0.1 pack is a draft product mapping for DORA Regulation (EU) 2022/2554 Article 9(4)(e) and Commission Delegated Regulation (EU) 2024/1774 Article 17. It is not legal advice, certification, a conclusion that an entity complies with DORA, or a guarantee of auditor or regulator acceptance. Qualified ICT-risk/compliance review is required before operational reliance.

## 3. Critical hypotheses — Kill Assumptions

Progress is measured by evidence that validates or falsifies these assumptions, not by code volume.

| ID | Hypothesis | Evidence required | MVP validation |
|---|---|---|---|
| H1 — Auditor acceptance | An independent auditor can understand and judge the manifest without the builder explaining it. | Dated, written feedback on a real, redacted sample, including gaps and rejected evidence. | Give an external auditor the sample and ask them to explain its outcome and limitations without coaching. |
| H2 — Customer pain | Manual preparation of ICT change-management evidence consumes enough time, cost or rework to justify change. | Baseline hours, roles, handoffs, systems and rework for a representative evidence request. | Measure the current manual process and compare it with the same change processed through the pack. |
| H3 — Willingness to pay | A named budget owner will fund the outcome, not merely praise the concept. | A priced pilot proposal with scope, deliverables, decision date and a written response; strongest proof is a signed order or payment. | Present a paid pilot proposal and record the actual procurement decision. Verbal interest is only a lead. |
| H4 — Technical evidence value | Exact SHA-bound provenance and integrity add value beyond a readable report. | Buyer/auditor feedback identifying a concrete decision or risk improved by source and artifact binding. | Compare a plain report with a source-bound manifest and record what the customer values and why. |

Each hypothesis is recorded as `VALIDATED`, `FALSIFIED` or `UNKNOWN`, together with date, evidence reference, source, participant role, confidence and resulting decision. Do not treat GitHub stars, downloads, internal opinion or positive comments as proof of willingness to pay.

## 4. The product is the Evidence Manifest

The Evidence Manifest is the only primary customer-facing output in the MVP. Collectors, adapters, validators, schemas, CI workflows, runtime, agents and storage are implementation means — not separate products to sell.

For one ICT change, the manifest must expose:

- the regulatory/control reference and limits of the mapping;
- control outcome: `PASS`, `FAIL`, `PARTIAL`, `BLOCKED`, `UNKNOWN`, `SKIPPED` or `NOT_APPLICABLE`;
- evidence integrity: `VERIFIED`, `INVALID` or `UNVERIFIED`;
- human approval: `APPROVED`, `PENDING` or `REJECTED`;
- evidence references, declared source identity and capture time;
- tenant, repository, change ID, full source commit SHA and released-artifact digest;
- missing evidence, exceptions, verifier results and limitations;
- a clear `READY` / `NOT_READY` result that cannot disguise a non-pass state.

`SKIPPED != PASS`. `NOT_APPLICABLE != PASS`. `UNKNOWN` is never promoted. Control result, evidence integrity and approval are independent axes. A digest proves byte consistency against the supplied bytes; it does not prove source truth, collection authority, role independence, control effectiveness or legal compliance. A digest is not a digital signature.

## 5. MVP proof: one complete change

The demonstration must cover one representative software-related ICT change on one repository:

1. Change request, purpose, scope and risk assessment.
2. Requester, implementer and approver identities, with an independent approval check.
3. Pull request and review evidence.
4. CI tests and security checks.
5. Exact source commit SHA and released-artifact digest.
6. Deployment record and post-deployment verification.
7. One self-contained Evidence Manifest showing evidence, missing items, state axes, source bindings and a recomputable manifest digest.

Where a source is not integrated, the evidence must be explicitly marked as manually supplied. The validator must fail closed on missing evidence, digest or binding mismatch, unapproved source types and self-approval conflicts. For DORA-CM-04 v0.1 checks consistency of supplied principal IDs and the role-relationship record; it does not authenticate those identities against an external identity/HR system.

A synthetic bundle that correctly returns `NOT_READY` is a successful fail-closed test. It is not proof of customer readiness, auditor acceptance or regulatory compliance.

## 6. The wall: deliberate non-goals for the first 60 days

Do **not** build or expand these before a paid pilot or a new evidence-backed decision:

- Knowledge Graph or graph database;
- dashboard or visual compliance portal;
- AI Auditor or autonomous legal/compliance interpretation;
- NIS2, ISO 27001, SOC 2 or other regulatory packs;
- marketplace;
- multi-tenant commercial platform;
- new runtime, new agent families or a second evidence gateway;
- broad source-adapter coverage beyond what is necessary to prove the one-change scenario;
- certification claims or a certification organisation.

Keep the existing OLA di-OS as the execution and verification technology. OLA Integrity Layer is the commercial evidence-translation product. OLA Evidence Packs are versioned regulatory products. A customer must be able to evaluate the pack without adopting the whole OLA runtime.

## 7. Chief Focus Officer rule — feature admission

Every proposed task must answer all five questions before entering the MVP:

1. Which of H1, H2, H3 or H4 does it test?
2. What observable result would support or falsify that hypothesis?
3. Why can the pilot not obtain this evidence manually?
4. What is the smallest change that produces the evidence?
5. What is the stop condition if the hypothesis is falsified?

If a task cannot show a direct, testable contribution to H1–H4, it goes to the strategic backlog. Technical interest is not an exception.

## 8. Thirty-day success criteria

At day 30, produce an evidence-based `GO`, `CHANGE` or `STOP` decision. The minimum evidence is:

1. One working DORA Evidence Manifest for one real or controlled pilot change on one repository.
2. One end-to-end demonstration from request and approval through PR, CI, commit, released artifact, deployment and verification.
3. At least five customer/auditor conversations, a measured baseline for H2, a comparative H4 demonstration and a priced-pilot discussion with a named budget owner.
4. H1–H4 each classified as `VALIDATED`, `FALSIFIED` or `UNKNOWN`, with supporting evidence.

Code volume, module count, dashboard views, stars and downloads are not success criteria.

## 9. Commercial hypotheses

Subscription per organisation is the current pricing hypothesis, not a validated price. €1,500/month Starter and €3,000+/month Enterprise are test points only. Every pilot offer must state repository scope, regulatory pack, evidence retention, integrations, support and service levels.

Track the commercial sequence separately: `INTEREST` → `TECHNICAL VALIDATION` → `OPERATIONAL VALIDATION` → `PROOF OF VALUE` → `PRICED PILOT` → `PAYMENT` → `RENEWAL`. A signed pilot is not a renewal; an intent to renew is not actual retention.

## 10. Product boundary and review trigger

- **OLA di-OS:** execution runtime, agent orchestration, execution boundaries and system security.
- **OLA Integrity Layer:** commercial evidence translation, validation and manifest generation.
- **OLA Evidence Packs:** versioned control-to-evidence contracts for a defined process and regulation.

Review this charter after 30 days or sooner if any of H1–H4 is falsified. Change the strategy based on observed evidence, not enthusiasm or sunk engineering cost.