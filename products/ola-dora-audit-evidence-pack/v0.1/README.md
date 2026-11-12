# OLA DORA Audit Evidence Pack — ICT Change Management v0.1.0

**Status: DRAFT / pilot validation only.** A portable, versioned control-to-evidence contract for one ICT change, from request through controlled implementation and post-implementation verification.

## Product promise
Translate technical and process artefacts into traceable evidence linked to a named control, authoritative source, tenant, change ID, exact repository, full source commit SHA and released-artifact digest.

This pack does not certify an organisation, establish full DORA compliance, replace an entity's approved policy, provide legal advice, or guarantee auditor/regulator acceptance. The mapping requires qualified ICT-risk/compliance review and independent auditor feedback before commercial reliance.

## Regulatory scope
- Regulation (EU) 2022/2554 (DORA), Article 9(4)(e): documented policies, procedures and controls for ICT change management, integrated into the overall change process, so changes are recorded, tested, assessed, approved, implemented and verified in a controlled manner.
- Commission Delegated Regulation (EU) 2024/1774, Article 17(1)(a)–(g): security requirements; independence of approval; roles/responsibilities and planning; transition; testing, controlled finalisation and QA; change purpose/scope/timeline/outcomes; fallback/abort/recovery; emergency-change safeguards; and post-implementation documentation/re-evaluation/assessment/approval for emergency changes, workarounds and patches.
- Article 17(9): ICT systems developed or managed by users outside the ICT function remain subject to risk-based application.

The catalogue contains twelve draft control objectives. v0.1 focuses on software-change evidence; hardware, firmware, system and security-parameter changes require manually supplied evidence. This is a product mapping, not a legal interpretation that every customer can apply unchanged.

## Verdict contract
- Control result: PASS, FAIL, PARTIAL, BLOCKED, UNKNOWN, SKIPPED, NOT_APPLICABLE.
- Evidence integrity: VERIFIED, INVALID, UNVERIFIED.
- Approval: APPROVED, PENDING, REJECTED.
- SKIPPED is never PASS. NOT_APPLICABLE is never PASS. UNKNOWN is never promoted.
- PASS requires all evidence types in the control catalogue, valid recomputed payload digests, exact repository/change/commit/artifact binding and an approved reviewer identity/role/time.
- A SHA-256 digest establishes consistency against the recorded bytes; it does not prove source truth, collection authority, role independence or legal compliance.
- A local READY result means only that this bundle satisfies this pack's contract. It is not legal compliance, auditor acceptance or certification.

## Contents
- controls/dora/ict-change-management.yaml — twelve draft controls mapped to DORA/RTS provisions.
- mappings/knowledge-graph.yaml — versioned regulatory requirement → control → evidence type → source type relationships; no graph database.
- policies/verdict-policy.yaml — independent result, integrity and approval axes.
- schemas/ — JSON Schemas for evidence and control verdict records.
- verification/ — source/artifact binding and pack-release attestation policy.
- examples/unverified-demo-bundle.json — synthetic incomplete bundle, expected NOT_READY.
- scripts/verify_pack.py — deterministic fail-closed validator.
- scripts/build_pack.py — deterministic ZIP builder.
- tests/ — positive-contract, negative, tamper and packaging tests.
- reports/auditor-report-template.md — report template with explicit limitations.

## Run locally
Python 3.11+:
\`\`\`bash
python -m pip install -r requirements.txt
python scripts/verify_pack.py examples/unverified-demo-bundle.json
python -m pytest -q
python scripts/build_pack.py --output dist/ola-dora-audit-evidence-pack-v0.1.0.zip
\`\`\`
The demo exits successfully as a valid but NOT_READY bundle; it is not a live customer record.

## Evidence sources expected for a pilot
| Source | Expected evidence | Does not prove alone |
|---|---|---|
| ITSM/change management | Change ID, requester, scope, risk, timeline, expected result, fallback | Actual code deployed |
| GitHub/GitLab | PR, diff, reviews, identities, commit SHA, CI | Role independence without role resolution |
| Identity/HR role source | Stable identities and roles | Approval bound to this change without an event link |
| CI/build | Tests, security checks, build result | Runtime deployment |
| Deployment platform | Environment, actor/time, artifact digest, outcome | Adequacy of testing |
| Post-deploy monitor/test | Health, smoke/functional result and time | Overall policy adequacy |
| Policy/approval repository | Approved policy, management approval, version | Operation of every individual change |

No customer source adapters are included in v0.1. The validator consumes a portable JSON evidence bundle; it does not connect to GitHub, Jenkins, GitLab, Jira, ServiceNow, an IdP or Railway.

## Pack release attestation
The root workflow .github/workflows/dora-audit-evidence-pack.yml validates and packages this directory. On a push to main it creates a GitHub Artifact Attestation for the exact ZIP using Sigstore-backed signing. Verify:
\`\`\`bash
gh attestation verify ola-dora-audit-evidence-pack-v0.1.0.zip --repo krzysztofcieciwa07-ship-it/OLA
\`\`\`
This attests the pack ZIP build provenance only. It does not attest customer source/deployments or certify the legal mapping. Customer artifacts require a separate source-bound attestation and trust policy.

## Legal sources
- DORA Regulation (EU) 2022/2554, Article 9(4)(e): https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2554
- Commission Delegated Regulation (EU) 2024/1774, Article 17: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1774

**Legal source-text review date:** 12 November 2026. This is not legal advice. Re-check the official EUR-Lex text, corrigenda and amendments before each pack release.
