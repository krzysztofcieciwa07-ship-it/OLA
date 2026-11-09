# Proposed GitHub Repository Metadata

**Status:** proposal only — no repository description, homepage, topic, visibility or name was changed.

The text below is intended for GitHub's repository settings after canonicalisation decisions are accepted.

## Canonical product repositories

### OLA — `krzysztofcieciwa07-ship-it/OLA`

**Description**

> Evidence-driven AI execution runtime for bounded agent workflows, tenant-scoped evidence, provenance, replay and independent verification.

**Suggested topics**

`ai-agents`, `ai-runtime`, `fastapi`, `python`, `evidence-provenance`, `auditability`, `security-engineering`, `replay-verification`, `tenant-isolation`

**Homepage**

Set only to an official OLA product or documentation domain after the domain's ownership and source-to-deployment relationship are verified. Do not point it at an unrelated preview.

### Vantage v0.3 — `krzys167-crypto/Vantage-v0.3`

**Description**

> Reproducible SRE/DevOps incident-response range for fault injection, SLO measurement, evidence-based scoring and verified recovery drills with Docker and k3d.

**Suggested topics**

`sre`, `devops`, `chaos-engineering`, `incident-response`, `fault-injection`, `slo`, `docker`, `k3d`, `kubernetes`, `evidence`

**Homepage**

Set only to the verified Vantage product or documentation domain. Current write access to this repository is not available through the connected GitHub integration.

### Quantum AI Chatbot — `krzysztofcieciwa07-ship-it/quantum-ai-chatbot`

**Description**

> Mobile-first AI chat application with Supabase authentication, conversation history and experimental server-side Google and Microsoft connectors.

**Suggested topics**

`ai-chatbot`, `react`, `typescript`, `vite`, `supabase`, `oauth2`, `google-api`, `microsoft-graph`, `pwa`

**Homepage**

Keep the current project URL only while its ownership, deployment source SHA and security posture remain verified. Do not describe this app as part of the OLA core runtime.

## Supporting and prototype repositories

### Vantage prototype — `krzysztofcieciwa07-ship-it/vantage`

**Description**

> Experimental deterministic risk-gate and LLM-routing prototype with a separate CFR-18 incident-forensics exercise.

**Suggested topics**

`risk-engine`, `llm`, `security-prototype`, `incident-forensics`, `python`

### OLA Evidence Gateway — `krzysztofcieciwa07-ship-it/ola-evidence-gateway`

**Description**

> Specification for OLA evidence collection, provenance, integrity verification and export; this repository does not currently contain a running gateway implementation.

**Suggested topics**

`evidence`, `provenance`, `audit-logging`, `specification`

**Homepage**

Remove the unrelated weather-site URL only after the repository metadata write capability is available and an official destination is confirmed.

## Repositories that should not be presented as proprietary products

Upstream forks such as MetaGPT, GitHub CLI, Vercel AI SDK, Homebrew, GitHub Docs and SwarmClaw must remain visibly identified as forks and must not be included in the OLA product showcase as original products. Preserve their upstream attribution and license.

## Metadata acceptance checklist

- [ ] Canonical repository confirmed.
- [ ] Description matches code on the default branch.
- [ ] Homepage domain ownership and source binding verified.
- [ ] Topics describe implemented functionality, not roadmap claims.
- [ ] Fork relationship and upstream attribution preserved.
- [ ] License reviewed.
- [ ] Product readiness and certification claims match independent evidence.
