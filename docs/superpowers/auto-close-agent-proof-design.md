# Auto-close Agent Proof Design

## Goal
Close the remaining semantic evidence gap without promoting capability execution to six independent AI agents without proof.

## Proof target
The runtime must demonstrate six independently instantiated agent executions, each with:
- a distinct agent execution identity;
- explicit input/context boundary;
- model/provider invocation evidence (or an explicit verified local deterministic substitute, clearly labeled);
- output evidence;
- provenance linking the execution to the repository commit and E2E run;
- independently verifiable evidence.

## Current baseline
Commit `302c133edf1ff0b3629af8579295252e5b90685d` already proves six capability paths, evidence records, independent verification, hash-chain integrity, runtime fault/recovery, CI, artifact and SHA-256 provenance.

## Implementation boundary
Do not rewrite the existing E2E gate. Add the smallest runtime contract that makes independence observable and independently verifiable. Do not claim external LLM/model calls unless runtime evidence contains the provider/model/call identifiers and the verifier checks them.

## Verification
The workflow must execute the new proof, run an independent verifier in a separate process, capture the runtime evidence artifact, verify its SHA-256 digest, and retain commit/run provenance.
