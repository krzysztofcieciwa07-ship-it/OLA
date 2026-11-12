# OLA Integrity Layer — Decision Charter v1.0

**Status:** ACTIVE — product scope and decision authority  
**Effective date:** 2026-11-12  
**Review cadence:** weekly during the first 30-day validation cycle

## 1. North Star

> OLA Integrity Layer shortens the path from a software change to an auditable, independently verifiable evidence package.

The product translates software-supply-chain and change-management artefacts into traceable evidence mapped to defined control objectives. It does not certify an organisation, provide legal advice, or guarantee regulatory or auditor acceptance.

## 2. The wedge: one problem, one buyer segment, one process

- **Problem:** technical and organisational evidence for ICT change management is fragmented and must be manually assembled and explained.
- **Initial customer segment:** regulated financial entities in scope of DORA; validate precise entity scope before qualification.
- **Initial process:** one ICT change, from request and risk assessment through approval, implementation, deployment and post-implementation verification.
- **Initial regulatory focus:** DORA Article 9(4)(e) and relevant requirements in Commission Delegated Regulation (EU) 2024/1774 Article 17. The mapping is a product hypothesis and requires qualified legal/compliance review.

## 3. Product and value proposition

**For Engineering:** a versioned DORA Audit Evidence Pack with schemas, policies, validation and CI integration.

**For ICT Risk / Compliance / auditors:** an Evidence Manifest stating what was checked, results, evidence references, exact repository and commit, deployed artifact digest, provenance, approvals, missing items and limitations.

The product is the manifest and the defensible chain of evidence behind it. Collectors, agents, graphs, dashboards and runtime services are implementation details unless they directly improve a validation hypothesis.

## 4. Critical assumptions — Kill Assumptions

A hypothesis is not validated by internal opinion, a successful unit test, GitHub stars or a demo watched by the team. Record customer role, evidence, date, exact observation, counter-evidence and decision.

| ID | Critical hypothesis | Evidence required | Validation method | Kill / pivot signal |
|---|---|---|---|---|
| H1 — Auditor acceptance | An independent auditor can understand the manifest and identify its limits without author-led explanation, and considers the evidence useful for a named control. | Written feedback tied to a sample manifest; gaps and supplementary evidence identified. | Walk through a synthetic or customer-authorised change with an external auditor. Do not call feedback formal acceptance unless explicitly granted. | Auditor cannot interpret it, rejects its evidence model, or requires manual reconstruction that removes the value. |
| H2 — Pain and urgency | Evidence collection for ICT change management consumes material time, creates audit friction or delays. | Baseline hours, roles, systems, number of repositories/changes, rework and deadlines. | Interview ICT Risk/Compliance and Engineering; measure one current-state evidence collection. | Pain is infrequent, low-cost, already solved, or has no accountable owner. |
| H3 — Willingness to pay | A qualified organisation will allocate budget for a paid pilot or subscription. | Named budget owner, scoped pilot, procurement path and written commercial next step; strongest proof is payment. | Offer a fixed-scope paid pilot with explicit success criteria. | Positive feedback without budget, owner, procurement action or willingness to pay. |
| H4 — Technical differentiation | Exact SHA/artifact binding and independently verifiable provenance materially increase trust or reduce review effort beyond a readable report alone. | Buyer/auditor comparison of report-only vs source-bound evidence; observed effect on review effort and confidence. | Demonstrate both views and ask which evidence changes the decision and why. | Customers value only formatting/aggregation and do not value cryptographic/source binding enough to pay. |

**Decision rule:** after at least five qualified customer conversations and one independent auditor review, classify each hypothesis as VALIDATED, INVALIDATED or INCONCLUSIVE, with evidence links. Do not force a positive result.

## 5. 30-day MVP success criteria

The cycle succeeds only if all three workstreams produce evidence:

1. **Working product:** DORA Audit Evidence Pack v1 validates one end-to-end ICT change on an independent repository. The manifest binds exact repository identity, full commit SHA, artifact digest, evidence records, approvals and verification outcomes.
2. **Demonstrable value:** a before/after walkthrough measures time and manual steps needed to assemble and review evidence. Missing, skipped, unknown and non-applicable states remain explicit.
3. **Market learning:** H1–H4 are each classified from real conversations and artefacts, with at least five qualified customer conversations and one independent auditor review attempted. A paid pilot offer is presented to a qualified budget owner.

A technically passing pack alone is not business success. A positive interview alone is not willingness-to-pay validation.

## 6. The wall — explicit 60-day non-goals

Do **not** build during the first 60 days unless new customer evidence changes this charter:

- a dedicated Knowledge Graph database or graph platform;
- a dashboard or visual analytics product;
- an AI Auditor or autonomous legal interpretation;
- NIS2, ISO 27001, SOC 2 or additional regulatory packs;
- a marketplace;
- a multi-tenant Evidence Engine/platform;
- a new generic runtime, gateway, collector framework or parallel persistence layer.

The existing OLA runtime and evidence components may be reused only where they reduce time to validate H1–H4. Do not expand them for architectural completeness.

## 7. Decision filter for every proposed task

A task enters the 30-day MVP only if its owner states:

1. Which hypothesis (H1, H2, H3 or H4) does it test?
2. What observable evidence will it produce?
3. Which customer, auditor or independent system will provide that evidence?
4. What is the smallest implementation that can produce it?
5. What is the acceptance criterion and kill/pivot threshold?

If no hypothesis is materially advanced, the task goes to the strategic backlog. Future scalability, AI capability, clean architecture and marketplace readiness are not sufficient reasons.

## 8. Evidence-state integrity

Control outcome, evidence integrity and approval are separate axes.

- **Control outcome:** PASS, FAIL, PARTIAL, BLOCKED, UNKNOWN, SKIPPED, NOT_APPLICABLE.
- **Evidence integrity:** VERIFIED, INVALID, UNVERIFIED.
- **Approval:** APPROVED, PENDING, REJECTED.

SKIPPED is never PASS. NOT_APPLICABLE is never PASS. A cryptographic digest proves byte consistency against a recorded digest; it does not prove source truth, authorised collection, role independence, control effectiveness or legal compliance. A READY pack result is not a legal opinion, certification or auditor acceptance.

## 9. Buying roles and commercial hypothesis

- **Economic buyer:** CTO or CISO.
- **Problem owner:** Head of ICT Risk / Compliance.
- **Technical user:** Head of DevSecOps / Engineering.
- **Evidence recipient:** internal or external auditor.

Initial pricing hypotheses (not validated): €1,500/month Starter and €3,000+/month Enterprise. Do not publish as established pricing until pilot scope, willingness to pay, support obligations, retention, repository/regulation limits and procurement feedback are validated.

## 10. 30-day execution sequence

| Days | Work | Exit evidence |
|---|---|---|
| 1–5 | Inventory existing OLA Integrity components and choose reuse boundaries | Verified inventory; no duplicate runtime/store |
| 6–10 | DORA Pack v1 and complete change scenario | Validated schemas, policies, positive and negative tests |
| 11–15 | Independent-repository installation | Reproducible run and source-bound manifest |
| 16–20 | Customer discovery | At least five qualified conversations; measured baseline pain |
| 21–25 | Auditor/customer walkthrough and pricing | Written feedback, gaps, scoped pilot offer |
| 26–30 | Paid pilot attempt and hypothesis decision | Commercial next step or explicit pivot decision |

## 11. Decision governance

This charter supersedes informal feature requests for the first 60-day validation window. Changes require written rationale, new customer evidence, impact on H1–H4 and an explicit owner decision. Record outcomes in the project decision log. This charter does not authorise production deployment or changes to customer environments.

## 12. References and claim boundaries

- Regulation (EU) 2022/2554 (DORA), Article 9(4)(e): https://eur-lex.europa.eu/eli/reg/2022/2554/oj
- Commission Delegated Regulation (EU) 2024/1774, Article 17: https://eur-lex.europa.eu/eli/reg_del/2024/1774/oj

Legal mappings must be rechecked against current official text and reviewed by qualified specialists before external reliance. This charter is a product decision document, not legal advice.
