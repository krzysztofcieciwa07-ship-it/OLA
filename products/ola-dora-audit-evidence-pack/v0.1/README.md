# OLA DORA Audit Evidence Pack — ICT Change Management v0.1.0

**Status: DRAFT / pilot validation only.** This pack defines a portable evidence contract for one software-related ICT change. Its only primary customer-facing output is an Evidence Manifest.

## Mission

Translate technical and process artefacts into traceable evidence that an auditor or control owner can inspect without relying on an undocumented explanation from the product author.

## Scope

- Regulation (EU) 2022/2554 (DORA), Article 9(4)(e).
- Commission Delegated Regulation (EU) 2024/1774, Article 17.
- One process: request, assessment, independent approval, implementation, deployment and post-implementation verification of a software change.
- Twelve draft control objectives are listed in `controls/controls.json`.

This is a draft product mapping, not legal advice, certification, a conclusion that an organisation complies with DORA, or a guarantee of auditor or regulator acceptance. A qualified ICT-risk/compliance specialist must review the mapping before operational reliance.

## Evidence contract

Every bundle binds:
- repository in `owner/name` form;
- change identifier;
- exact 40-character source commit SHA;
- released-artifact SHA-256 digest;
- per-control result and evidence references;
- evidence payload digests;
- declared reviewer and approval state.

Control result, evidence integrity and approval are separate axes:

- Control: `PASS`, `FAIL`, `PARTIAL`, `BLOCKED`, `UNKNOWN`, `SKIPPED`, `NOT_APPLICABLE`.
- Evidence integrity: `VERIFIED`, `INVALID`, `UNVERIFIED`.
- Approval: `APPROVED`, `PENDING`, `REJECTED`.

`SKIPPED != PASS`. `NOT_APPLICABLE != PASS`. A valid digest proves consistency against the recorded bytes; it does not prove source truth, collection authority, role independence, control effectiveness or legal compliance.

## Deliberate MVP exclusions

For the first 60 days, this product does not build a Knowledge Graph/database, dashboard, AI Auditor, NIS2/ISO/SOC 2 packs, marketplace, multi-tenant commercial platform, broad source-adapter suite or second runtime. The existing OLA di-OS remains separate execution technology.

A feature enters the MVP only when it directly produces observable evidence for hypothesis H1 (auditor comprehension/acceptance), H2 (customer pain), H3 (willingness to pay) or H4 (incremental value of independently verifiable SHA-bound evidence).

## Current limitations

- The validator consumes a portable JSON bundle; it does not connect to GitHub, GitLab, Jira, ServiceNow, Jenkins, an identity provider or a deployment platform.
- It checks the declared repository/commit/artifact binding fields and recomputes each supplied evidence-payload digest. It does **not** independently fetch a released artifact and recompute its digest, or prove that the declared commit produced that artifact.
- Reviewer identity and role are declared bundle fields; v0.1 does not authenticate them against an external identity/HR source or prove separation of duties independently.
- Manifest SHA-256 is a digest, not a digital signature. Customer-manifest signing is `NOT_ISSUED`.
- The validator is a contract checker, not an auditor and not a legal conformity assessment.

## Run locally

Python 3.11+; standard library only:

```bash
python products/ola-dora-audit-evidence-pack/v0.1/scripts/verify_bundle.py \
  products/ola-dora-audit-evidence-pack/v0.1/examples/incomplete-bundle.json \
  --output evidence-manifest.json
python -m unittest discover -s products/ola-dora-audit-evidence-pack/v0.1/tests -v
```

The example intentionally produces `NOT_READY` with missing controls recorded as `UNKNOWN`. This is a successful fail-closed demonstration, not customer readiness.

## Regulatory sources

- DORA: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2554
- Delegated Regulation (EU) 2024/1774: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1774

**Legal source review date:** 12 November 2026. Re-check official EUR-Lex text, corrigenda and amendments before each pack release.
