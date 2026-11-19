# OLA 24x7 Watchdog: operator semantics and SLI mapping

## Scope

This runbook defines how to interpret the lifecycle artifact produced by
`.github/workflows/ola-24x7-watchdog.yml`. It applies to one exact Watchdog
run and its recorded source commit. It does not authorize terminal execution,
deployment, or production acceptance.

## Control success is not runtime health

A green GitHub Actions conclusion means that the Watchdog control job completed
without an unhandled workflow failure. It does **not** prove that the current
main revision has a verified evidence chain.

In particular, `decision=CONTINUE` means that the controller selected a safe
next action. It is not equivalent to `evidence_status=VERIFIED`. Never derive
a `runtime_healthy` SLI from the workflow conclusion alone.

## Lifecycle state interpretation

| Decision | Action | Evidence status | Meaning | Operator response | Health classification |
|---|---|---|---|---|---|
| `CONTINUE` | `WAIT` | `UNKNOWN` | An eligible main flow is still active. | Do not dispatch a duplicate. Recheck the exact flow and its terminal result. | `INDETERMINATE`, not healthy. |
| `CONTINUE` | `WAIT` | `BLOCKED` | The Watchdog checkout is stale because main advanced, or the current source could not be safely bound. | Do not reuse old evidence or dispatch from the stale checkout. Wait for a run on the current main SHA. | `BLOCKED`. |
| `CONTINUE` | `DISPATCHED` | `UNKNOWN` | No successful 12h flow exists for the exact current main SHA; a new flow was requested. | Capture the dispatch reference, then monitor the resulting run and compare its `head_sha` with current main. | `PENDING`, not verified. |
| `CONTINUE` | `DISPATCHED` | `VERIFIED` | The exact-SHA evidence passed verification but exceeded the 12-hour freshness window. | Monitor the refresh flow. Do not report current evidence as fresh until the new flow verifies. | `STALE` until refreshed. |
| `CONTINUE` | `NONE` | `VERIFIED` | Exact-main flow, required jobs, aggregator digest, nested artifact copies, provenance and IGOR checks passed and the evidence is fresh. | Retain the lifecycle artifact and its run/artifact identifiers as the evidence record. | `EVIDENCE_VERIFIED` for this SHA only. |
| `HUMAN_GATE` or `STOP` | `NONE` | `BLOCKED` or `UNKNOWN` | A required gate, provenance check, artifact check, GitHub request or internal operation failed closed. | Open or update an incident. Preserve the run and artifact IDs; do not retry blindly or promote the result. | `BLOCKED`. |

The combinations above are semantic states, not interchangeable labels. An
operator dashboard must display `decision`, `action`, `evidence_status`,
`reason`, `source_sha`, `current_main_sha`, `flow_run_id` and
`flow_sha` separately.

## Required evidence predicates

A lifecycle record can be classified as `EVIDENCE_VERIFIED` only when all of
the following are true:

1. `source_sha == current_main_sha`.
2. The selected 12h flow is on `main`, uses an allowed event, has the exact
   same `head_sha`, and has a terminal successful conclusion.
3. The required preflight, NINA/Ollama, independent IGOR and classification
   jobs succeeded in that same flow run.
4. The AUTO artifact is uniquely identified, unexpired, non-empty, and its
   downloaded archive digest matches the GitHub artifact API digest.
5. Nested preflight, NINA and IGOR copies are independently downloaded and
   verified; their source, run identity, file manifests and cross-copy
   consistency checks pass.
6. The aggregator summary checksum and schema pass; IGOR, hash chain and
   replay are verified; tamper is blocked; Human Gate remains pending.
7. The evidence is no older than 12 hours, measured from successful flow
   completion rather than flow creation.

A main SHA change invalidates freshness for the new source. Evidence from an
older SHA must not be carried forward as proof for the new SHA.

## SLI and alerting rules

Measure the control plane and evidence plane separately:

- **Watchdog execution availability:** observed scheduled Watchdog run IDs
  divided by expected five-minute schedule ticks. Alert on a gap greater than
  15 minutes. This measures scheduler/control-plane liveness only.
- **Exact-main evidence freshness:** age of the newest `EVIDENCE_VERIFIED`
  lifecycle record whose `source_sha` and `flow_sha` equal the current
  `main` SHA. The target freshness window is 12 hours. Reset the measurement
  when main advances.
- **Evidence verification rate:** count only terminal evaluations with
  `evidence_status=VERIFIED` and all required artifact predicates satisfied.
  Exclude `WAIT`, `DISPATCHED`, `UNKNOWN`, `BLOCKED` and skipped gates
  from the verified numerator.
- **Dispatch completion latency:** measure from the Watchdog dispatch request
  to the terminal result of the resulting 12h flow on the same exact SHA.
  A dispatch request by itself is not a successful flow.
- **Provenance alignment:** record whether `source_sha`, `current_main_sha`
  and `flow_sha` match. Any mismatch is a blocked evaluation, never a
  successful health sample.

A green Watchdog job with `WAIT/UNKNOWN`, `WAIT/BLOCKED` or
`DISPATCHED/UNKNOWN` must not increase the verified-evidence numerator.
Report missing scheduled run IDs as missing observations, not as successful
health checks.

## Operator procedure

1. Open the Watchdog run and download its lifecycle artifact.
2. Confirm the artifact belongs to that run and inspect the fields listed
   above. Do not infer state from the GitHub conclusion badge.
3. Compare `source_sha` and `current_main_sha` with the current repository
   `main` reference. If they differ, do not reuse the evidence.
4. If a flow is active, wait for that exact run. If a flow was dispatched,
   locate its run ID and verify its `head_sha` before accepting any output.
5. For `evidence_status=VERIFIED`, independently retain the artifact IDs,
   GitHub digests, manifest hashes and nested IGOR verification result.
6. Keep Human Gate, public staging, production deployment and provider
   acceptance as separate decisions. Ollama evidence does not verify the
   OpenAI provider lane; one must never be substituted for the other.

## Release boundary

`EVIDENCE_VERIFIED` means only that the defined evidence chain is verified
for one exact main SHA and freshness window. It does not mean that production
is deployed, public staging is accepted, payments were executed, or Human Gate
was approved.
