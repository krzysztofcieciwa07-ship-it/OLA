# OLA Security Policy

## Scope

This policy covers the OLA runtime, evidence chain, agent execution, provenance, replay verification, human gate, CI/CD release gates, and published release artifacts.

## Supported versions

The intended release line is `main`. As of the audit recorded in the decision register, GitHub reports `main.protected=false`; the active ruleset only contains branch-deletion and non-fast-forward protections. Therefore effective review and required-check enforcement on `main` is **NOT_VERIFIED**. A commit on `main` is not, by that fact alone, a protected or production-accepted release. Development branches are not production releases and must not be used as production evidence.

## Security invariants

- Fail closed: an unknown or unverifiable state cannot become `ALLOW` or `VERIFIED`.
- Human approval is independent of caller-provided approval fields.
- Evidence-chain tampering must be rejected.
- Provenance mismatch must block promotion.
- Replay must independently verify the captured chain.
- Production promotion requires the final production gate.
- Release source and release artifacts are attested and independently verifiable in CI.

## Release evidence

A production release must retain the final production evidence bundle, including:

1. exact source commit;
2. source snapshot SHA-256;
3. signed GitHub build provenance attestation for the source snapshot;
4. release image SHA-256;
5. signed build provenance attestation for the release image;
6. CI, state-continuity, stability, provenance, runtime, stress, tamper and replay results;
7. final production manifest.

## Vulnerability reporting

Report suspected vulnerabilities privately to the repository maintainers through the repository's configured private security reporting channel. Do not disclose credentials, API keys, customer data, or exploitable proof-of-concept details in public issues.

If a private reporting channel is not configured, repository maintainers must configure GitHub private vulnerability reporting before declaring the project production-ready.

## Incident response

Security incidents must be classified, contained, evidenced, remediated, and independently verified before the affected release is promoted again. Evidence must preserve the original failing state and the remediation proof.

## Secrets and keys

Production credentials must not be committed to the repository. Keys used for release signing or external services must be rotated after suspected exposure. CI must use short-lived identity where supported and must not treat a static secret as proof of source provenance.

## Security claims

CI success is evidence for the executed checks only. It is not a claim of absolute security or immunity from compromise. `UNKNOWN` remains `UNKNOWN` until independently verified.


## Execution identity and approval roles

Paid-order execution uses separate tenant-scoped API identities:

- `tenant`: may submit work; cannot approve execution or customer report delivery.
- `execution_approver`: may approve a paid sandbox execution only when distinct from the requester. The role is checked when approval is created and rechecked immediately before worker dispatch.
- `report_reviewer`: may review the exact report digest and evidence tip only when distinct from both requester and execution approver.

Role assignment is an administrative operation. The application does not allow a tenant API key to promote itself or another key. Provision or revoke these roles only through a trusted database-administration path, record the change, and preserve the separation of duties.

The internal worker token authenticates the execution service; it is not a human approval and must not be shared with tenant clients. The paid-order worker is restricted to the registered `safe_expression` capability. A successful execution approval does not authorize deployment, production financial transfers, or external side effects.

If an approver role is removed or changed after approval but before dispatch, the worker must block the job and require manual reconciliation.


## Branch, push, merge, and PR closure policy

### Branch model

- `main` is the canonical integration branch. Do not make routine direct commits to it.
- Each change starts from the freshly read full SHA of `main` and uses a focused branch, for example `feat/*`, `fix/*`, `security/*`, `docs/*`, or `chore/*`.
- A branch push must be a normal fast-forward update. Force-push and history rewriting are prohibited for shared, reviewed, or evidence-bearing branches.
- Every PR must state its purpose, risk boundary, exact candidate SHA, checks actually executed, unresolved findings, and rollback procedure.
- A branch name, green badge, or open PR is not proof that the candidate is acceptable.

### Push rules

1. Fetch current `main` and record its full 40-character SHA.
2. Create a new topic branch from that exact SHA, or explicitly reconcile the branch with the current base before review.
3. Commit only scoped changes. Keep credentials, production data, signing keys, and runtime evidence containing sensitive values out of Git.
4. Push the topic branch without force. If the remote head changed, inspect the new head and reconcile; do not overwrite it.
5. Open a PR to `main`. Do not push directly to `main` as a substitute for review.
6. After each new commit, rerun the required checks against the new exact head SHA. A previous SHA's green CI does not transfer to a new commit.

### Merge gate

A PR is mergeable only when all of the following are true:

- the PR head is the exact SHA that was reviewed and tested;
- required tests, security scans, provenance checks, and Evidence Gate checks have completed successfully on that SHA;
- skipped, missing, stale, or mismatched checks are treated as BLOCKED, not PASS;
- at least one independent reviewer other than the PR author has approved the current change;
- stale approvals are dismissed after new commits; the latest push is reviewed as required by the configured rules;
- all blocking review threads are resolved;
- the PR base is the intended canonical branch and merge conflicts have been handled without discarding evidence;
- any required Human Gate is a separate identity-bound decision and is not replaced by an agent's recommendation.

Default repository merge preference: **squash** for a focused, self-contained change. Use a merge commit when preserving a reviewed multi-commit sequence is necessary for provenance. Do not use rebase as a way to evade review or required checks: rewritten commits require a new exact-SHA verification cycle.

After merge, record the PR number, merge commit SHA, resulting `main` SHA, and linked CI runs. Verify the new `main` SHA independently. If deployment is involved, compare the deployed image/source revision with that exact merge SHA and run health, readiness, and stability checks. Merge success is not deployment acceptance.

### PR closure and branch retention

- `MERGED`: close through an actual GitHub merge; verify the merge SHA and resulting base history.
- `CLOSED_UNMERGED`: this means the change was not integrated. Record why (superseded, duplicate, rejected, abandoned, or not planned).
- Before closing an unmerged PR, compare its head with its base and identify commits/files that would otherwise be lost. Confirm that any required work has been merged elsewhere or explicitly rejected.
- Closing a PR does not delete its source branch. Do not delete a branch until unique commits, review comments, artifacts, and evidence have been reconciled and retention is approved.
- Do not mass-close PRs or mass-delete branches based only on age, title, duplicate-looking names, or matching head SHAs.
- GitHub's repository configuration currently has automatic branch deletion after merge disabled. Keep that behavior until explicit retention policy and evidence archival are in place.

### Current governance limitation

The observed repository ruleset `25853037` is active but only specifies `deletion` and `non_fast_forward`; the branch endpoint reports `main.protected=false`. The connected integration cannot read the full effective branch-protection endpoint (HTTP 403). The owner/admin must activate and independently verify the required review/check policy in GitHub Settings. Do not claim branch protection is complete before a negative test proves that a PR without review or required checks is blocked.

## Agent and external-tool trust boundaries

- OLA's six named runtime roles currently execute in one Python process and are marked `execution_boundary=in_process`. They are capability paths, not six isolated autonomous agents.
- The runtime provider adapter currently supports OpenAI and Ollama. Gemini, Codex, and MetaGPT are not runtime-authorized providers merely because they are present in the engineering ecosystem or repository catalog.
- Codex and Gemini may prepare work on topic branches, but must not merge their own changes, approve their own work, alter branch protections, or deploy.
- MetaGPT is an external MIT-licensed framework/reference fork. It is not a dependency or a trusted execution boundary in OLA. Any future adapter must enforce OLA's identity, JSON schema, capability allowlist, sandbox, evidence, IGOR, and Human Gate contracts.
- Jev/TypeSafe is advisory only. Its output cannot set `VERIFIED`, authorize a merge, or create Human Gate approval.
- n8n may trigger approved OLA API operations but cannot bypass tenant authentication, NINA policy, Evidence Gate, IGOR, or Human Gate. Workflow credentials must be least-privilege and held in a secret manager.
- The Evidence Gateway repository currently represents specification/reference material, not an operational gateway endpoint.

## Evidence Gate — required acceptance sequence

Every consequential coding or runtime change follows this sequence:

1. **Source identity:** record repository, branch, and exact full source SHA.
2. **Scope and policy:** verify actor identity, tenant, requested capabilities, risk, and approval requirements.
3. **Execution:** run only allowlisted capabilities with bounded inputs, depth, concurrency, time, output size, and network destinations.
4. **Lifecycle evidence:** persist run start, per-step start/completion/failure, terminal run end, source revision, input/output digests, and artifact references.
5. **Integrity:** validate Evidence V4 signatures/hash chain, sequence, previous hash, tenant boundary, and immutable source binding.
6. **Independent verification:** IGOR recomputes the captured evidence; adversarial mutation must be rejected and replay must be deterministic.
7. **Policy and human decision:** derive the decision from evidence and policy; human approval must be an independent identity and bound to the verified digest/tip.
8. **Release provenance:** bind source, build, image/artifact digest, attestation, deployment revision, and runtime health to the same candidate.
9. **Stability:** require the defined health/SLI observation window before declaring release accepted.

Any missing, skipped, stale, mismatched, tampered, or unverifiable prerequisite blocks progression. `VERIFIED` is not equivalent to `HUMAN_APPROVED`; Human Gate is not equivalent to deployment authorization.

## License and third-party notices

The repository root LICENSE is **Unlicense** for the repository's own covered work. This does not change the license of separately maintained third-party projects or packages. Preserve third-party notices and license texts when copying or vendoring code. MetaGPT is MIT-licensed; include its applicable notices if any of its code is redistributed with OLA. A complete direct/transitive dependency license audit and SBOM are still required before product redistribution; do not claim full license compliance until they are generated and reviewed for the exact release SHA.


### CODEOWNERS and independent-review limitation

The current `.github/CODEOWNERS` maps the default paths to the single account `@krzysztofcieciwa07-ship-it`. That is not an independent reviewer when the same account authors the PR. The current ruleset-candidate script also sets `require_code_owner_review: false`, while `.github/SECURITY-BASELINE.md` lists CODEOWNERS review as a target control. These definitions are not yet aligned.

Do not treat the CODEOWNERS file as proof of independent review. Before claiming this control is effective, configure a separate trusted reviewer/team, align the candidate ruleset and documentation, and prove with a test PR that self-authored changes cannot satisfy the independent-review requirement.


## S…X cloud execution environment — identification and launch gate

The cloud environment referred to by the owner as **S…X** is a distinct resource whose provider and resource identity have not yet been established. Do not infer that it is a Vercel Sandbox, a Railway project, a Replit App, or any other similarly named resource.

Before any start, resume, clone, attach, deployment, or code execution, independently verify and record:

1. provider/account and owner/workspace identity;
2. immutable project ID and environment ID;
3. session/instance ID and snapshot ID/state, if applicable;
4. repository URL, branch/worktree and exact full source SHA;
5. image/runtime digest and configured entrypoint;
6. region, CPU/memory/disk limits, persistence and lifecycle/expiry;
7. outbound network allowlist, inbound exposure and secret custody;
8. authenticated operator identity and permitted actions;
9. health/heartbeat and a real run ID with start/end evidence.

A matching display name is not an identity. A stale/deleted snapshot is not a running environment. A successful provider control-plane response is not proof that the application is healthy or running the expected SHA.

**Current disposition: NOT_VERIFIED / DO_NOT_START.** The latest accessible Railway inventory contained the known OLA projects/environments but no unambiguous S…X name; Replit title searches for S-X/SX returned no apps. These checks cover only those connected inventories. A previous attempt to resume a particular Vercel resource returned `snapshot_not_found`; that resource must not be treated as S…X without an independently matching immutable identifier.

Do not expose provider credentials or secret values in reports. Record identifiers and redacted configuration metadata only. If the identity or source cannot be proven, fail closed and leave the resource untouched.
