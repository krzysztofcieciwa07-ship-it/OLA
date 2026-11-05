# CLI-Hub discovery adapter — OLA integration v0

## Purpose

Expose the public CLI-Hub catalogue to the existing OLA NINA workflow as one
read-only capability: `cli_hub_discover`. OLA remains responsible for tenant
identity, policy admission, workflow execution, Evidence, IGOR verification,
and Human Gate.

## Data flow

1. The existing NINA policy allowlist admits `cli_hub_discover`.
2. The workflow executor calls `app.cli_hub_discovery.search_catalog()`.
3. OLA downloads both registries used by the upstream CLI-Hub package:
   - `https://hkuds.github.io/CLI-Anything/registry.json` (first-party harnesses);
   - `https://hkuds.github.io/CLI-Anything/public_registry.json` (public CLIs).
4. OLA filters both registries locally. The user's query is not sent to either
   registry endpoint.
5. The adapter returns only descriptive fields: name, display name, version,
   description, category, and requirements.
6. Registry-supplied install commands, executable names, source instructions,
   and paths are never returned to the model as trusted instructions.
7. The existing workflow engine records the plan, start, output digest, result,
   and terminal event in tenant Evidence. IGOR can independently replay the
   captured event chain. This is still local evidence, not an upstream
   signature or proof that a CLI was executed.
8. The response remains `COMPLETED_UNVERIFIED` unless the normal independent
   verification conditions are met; Human Gate remains `NOT_APPROVED`.

## Bounds and fail-closed behavior

- Query: 1–120 characters.
- Each registry body: at most 512 KiB; combined maximum: 1 MiB.
- Both registries are required for `HARNESS_AND_PUBLIC` coverage; failure or
  invalid schema in either registry blocks the discovery rather than silently
  presenting an incomplete catalogue.
- Results: at most 20 across both catalogues.
- HTTP timeout: 8 seconds overall, 3 seconds connect.
- Redirects disabled.
- Invalid JSON/schema, timeout, HTTP failure, or oversized registry blocks
  execution; no fallback catalog is invented.
- One isolated root node only. CLI-Hub discovery cannot be combined with
  another capability or consume upstream execution output.
- No user query is sent over the network; only the static public registry is
  fetched and searched locally.

## Deliberate non-capabilities

This version does not install, update, uninstall, launch, or execute any
third-party CLI. It does not accept registry install commands as instructions.
It does not claim upstream cryptographic authenticity: the SHA-256 value binds
the exact bytes observed by this run, but does not prove who published them.

## Requirements before v1 execution support

A separate reviewed change must define, for every executable tool:
- approved source and immutable release/commit;
- package and binary digest verification;
- tool-specific argument schema and action allowlist;
- isolated execution sandbox, resource ceilings, timeout, and output limits;
- explicit Human Gate for external side effects;
- signed Evidence binding tenant, task, policy decision, tool/version, argv,
  exit status, artifact hashes, runtime identity, and exact source commit;
- independent IGOR replay and tamper tests.

The workflow remains behind `OLA_PARALLEL_WORKFLOWS_ENABLED=1` and the existing
real-LLM planning and Evidence/IGOR controls.
