# OLA Integrity Layer — Decision Charter v1.0

**Status:** ACTIVE PRODUCT SCOPE  
**Effective date:** 12 November 2026  
**Review horizon:** first 60 days of product validation

## 1. North Star

> OLA Integrity Layer shortens the path from a software change to an audit-ready evidence record.

The product translates technical and process artefacts from the software supply chain into traceable, cryptographically bound evidence that an auditor or control owner can understand and independently inspect.

## 2. The wedge: one problem, one customer, one process

| Dimension | MVP decision |
|---|---|
| Problem | Technical artefacts are not mapped consistently to evidence expected for ICT change-management controls. |
| Initial customer | A regulated financial entity in scope of DORA, initially reached through ICT Risk, Compliance, CISO or Engineering leadership. |
| Process | One software-related ICT change, from request and assessment through approval, implementation and post-implementation verification. |
| Regulatory focus | DORA Regulation (EU) 2022/2554, Article 9(4)(e), and Commission Delegated Regulation (EU) 2024/1774, Article 17. |
| First product | OLA DORA Audit Evidence Pack — ICT Change Management. |

The initial catalogue is a product mapping to be reviewed by qualified ICT-risk/compliance specialists. It is not legal advice, a certification, or a conclusion that an organisation complies with DORA. The pack's v0.1 validator accepts a portable JSON evidence bundle; source-system adapters and automatic customer evidence collection are not yet implemented.

## 3. Product value: the bridge

**For Engineering:** a versioned Audit Evidence Pack with control definitions, evidence contracts, fail-closed validation and a GitHub Actions entry point.

**For the auditor or control owner:** one Evidence Manifest for a specific change. It records control outcomes, missing evidence, evidence-integrity results, approval state and exact bindings to the repository, full commit SHA and released-artifact digest.

The Evidence Manifest is the only primary customer-facing output in the MVP. Collectors, schemas, validators, CI workflows and storage are implementation mechanisms, not separate products to sell.

A manifest digest is not a signature. A pack ZIP build attestation is not a customer-change attestation. v0.1 must disclose `NOT_ISSUED` for customer-manifest signing until a separate signing and trust policy is implemented.

## 4. Critical hypotheses — Kill Assumptions

No hypothesis is considered validated from internal opinion, code completion, GitHub stars or downloads. Each starts as `UNKNOWN` and must be updated with dated evidence.

| ID | Hypothesis | Evidence required | MVP validation |
|---|---|---|---|
| H1 — Auditor acceptance | An independent auditor or control assessor can understand the manifest and judge it useful without the product author explaining it. | Written, scoped feedback against a real sample manifest, including gaps and rejected evidence. | Walk an external auditor through one sample change and record acceptance, rejection or conditions. |
| H2 — Customer pain | Evidence preparation for ICT change management consumes enough time or money to justify change. | Customer baseline for people, hours, systems and rework for a representative evidence request. | Measure the existing manual workflow with a pilot candidate and compare the same change using the pack. |
| H3 — Willingness to pay | A named budget owner will fund the product, not merely praise the concept. | Written pilot proposal response from an identified economic buyer; strongest proof is a signed paid pilot or purchase order. | Present a scoped paid pilot with price, deliverables, timeline and acceptance criteria. Verbal interest is only a lead. |
| H4 — Technical evidence value | SHA-bound provenance and integrity materially improve trust or audit usefulness beyond a well-presented report. | Comparative feedback on a readable report with and without independently verifiable source/artifact binding. | Demonstrate both views and record which properties the buyer and auditor require and why. |

A hypothesis may be **SUPPORTED*), **REJECTED** or remain **UNKNOWN**. Record the evidence, source, date, participant role (without unnecessary personal data), confidence and resulting decision. A rejected hypothesis triggers a scope or positioning change; it is not hidden as a delivery success.

## 5. MVP success criteria — 30-day validation window

The 30-day outcome is an evidence-based decision, not a line-count or feature-count target. Success means we can answer H1–H4 with documented `SUPPORTED`, `REJECTED` or `UNKNOWN` outcomes and make a go / change / stop decision.

The product demonstration must:

1. Run the DORA Audit Evidence Pack against one independent repository or controlled pilot repository.
2. Trace one representative software change from request and risk assessment through independent approval, pull request, tests, exact commit SHA, released artifact, deployment and post-deployment verification. Where a source is not integrated, the manifest must identify the evidence as manually supplied.
3. Generate one self-contained Evidence Manifest with control states, evidence references, missing items, reviewer state, repository/commit/artifact bindings and a recomputable manifest digest.
4. Reject tampering, mismatched SHA/digest, missing required evidence, invalid source types and self-approval conflicts; never convert `SKIPPED`, `UNKNOWN` or `NOT_APPLICABLE` into `PASS`.
5. Capture customer and auditor feedback for H1–H4 and produce a documented decision.

A valid demo bundle that reports `NOT_READY` is a successful fail-closed test, not proof of customer readiness or regulatory compliance.

## 6. The wall: deliberate non-goals for the first 60 days

Do **not** build or expand the following before a paid pilot or new evidence-backed decision:

- a Knowledge Graph or graph database;
- a dashboard or visual compliance portal;
- an AI Auditor or autonomous legal/compliance interpretation;
- NIS2, ISO 27001, SOC 2 or other regulatory packs;
- a marketplace;
- a multi-tenant commercial platform;
- new agent families, a new runtime, or a second evidence gateway;
- broad source-adapter coverage beyond what is needed to prove the single change scenario.

The existing OLA di-OS runtime remains the execution and verification technology. OLA Integrity Layer is the commercial product boundary. OLA Evidence Packs are versioned regulatory products. Do not merge these identities or require customers to adopt the full OLA runtime to evaluate the pack.

## 7. Decision filter for every proposed feature

A proposal enters MVP only when its author identifies at least one direct, testable contribution to H1, H2, H3 or H4 and names the observable evidence it will produce. Otherwise it goes to the strategic backlog.

| Feature proposal | Required question |
|---|---|
| New integration or collector | Which missing evidence in the one-change flow does it collect, and which hypothesis does that unblock? |
| UI or dashboard | Does it materially improve auditor comprehension in H1, beyond the Evidence Manifest itself? |
| Cryptographic control | Does it change the result of H4 or make the exact change/artifact binding independently verifiable? |
| New regulation or module | Why is it necessary before a paid DORA pilot? |
| AI capability | What manual evidence work or interpretation does it remove, and how will a customer validate that safely? |

No contribution demonstrated means no MVP work.

## 8. Verdict and claim discipline

Control result, evidence integrity and approval are independent axes:

- Control: `PASS`, `FAIL`, `PARTIAL`, `BLOCKED`, `UNKNOWN`, `SKIPPED`, `NOT_APPLICABLE`.
- Evidence integrity: `VERIFIED`, `INVALID`, `UNVERIFIED`.
- Approval: `APPROVED`, `PENDING`, `REJECTED`.

`SKIPPED != PASS`. `NOT_APPLICABLE != PASS`. A valid digest proves consistency against recorded bytes; it does not prove source truth, collection authority, role independence, control effectiveness or legal compliance.

Do not use “certified”, “DORA compliant”, “auditor-approved” or “accepted by a regulator” without the corresponding independent, scoped and documented basis. The product reports what evidence was supplied, what the pack checked and what remains missing.

## 9. Commercial hypotheses

Subscription per organisation is the current pricing hypothesis, not a validated price. Starter at €1,500/month and Enterprise from €3,000/month remain test points for customer interviews and paid-pilot proposals. Each offer must specify repository scope, regulatory pack, retention, integrations, support and service levels.

GitHub stars, downloads and verbal enthusiasm are interest signals, not Product-Market Fit. Commercial validation requires paid use; retention requires real renewals or repeat purchases, with expansion and referrals tracked separately.

## 10. Product separation

- **OLA di-OS:** execution runtime, agent orchestration, execution boundaries and system security.
- **OLA Integrity Layer:** commercial evidence translation, validation and manifest generation.
- **OLA Evidence Packs:** versioned control-to-evidence contracts for a defined process and regulation.

The first commercial deliverable is the DORA ICT Change Management Evidence Manifest. Everything else must earn its place by reducing the distance from a real change to that manifest and by validating H1–H4.
