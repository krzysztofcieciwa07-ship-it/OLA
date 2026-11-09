# OLA Chaos Scenario DSL v0

Status: experimental contract for isolated, local fault-injection labs.

## Contract

A scenario is a versioned JSON document with these top-level sections:

- metadata: stable scenario ID, SemVer version and description.
- target: runtime, service endpoint, intended impact resources and collateral sentinels.
- fault: typed fault ID, injection strategy, parameters and schedule.
- traffic: load engine, VU count, strict TLS verification and request timeout.
- assertions: machine-verifiable requirements; unknown assertions are rejected.
- scoring: normalized weights, pass/merit/elite thresholds and explicit penalties.
- evidence: raw sources and a required Ed25519 manifest signature.
- anti_llm: run nonce, randomized timing, private policy, stability window and probe-gap limit.

The canonical schema is schemas/chaos-scenario-v0.schema.json.
The catalog is schemas/chaos-fault-catalog-v0.json. Only
tls_cert_expired is implemented by the v0 runner. invalid_truststore, time_skew,
dns_poison, kafka_lag and cpu_throttle are typed, reserved fault classes, not
currently executable plugins. A schema-valid reserved fault is not proof that
a runner implements it.

The first executable scenario is scenarios/certificate-apocalypse/scenario.json.

## v0 example

    {
      "apiVersion": "ola.di-os/chaos/v0",
      "kind": "Scenario",
      "metadata": {"id": "certificate-apocalypse", "version": "0.1.0",
                   "description": "Expired TLS leaf certificate and measured recovery."},
      "fault": {"id": "tls_cert_expired",
                "strategy": "atomic_certificate_pointer_swap"},
      "traffic": {"engine": "k6", "tls_verification": "required"},
      "anti_llm": {"per_run_nonce": true, "private_assertion_policy": true}
    }

The example above is abbreviated for orientation; executable scenarios must
validate against the complete JSON Schema.

## Invariants

1. Unknown or missing evidence is not a pass. Assertions fail closed.
2. The test binds only to 127.0.0.1; the Compose network is internal and no
   production endpoint can be selected by the scenario.
3. The expired certificate is rejected by clients with CA and hostname
   verification enabled. k6 is never configured with insecure TLS mode.
4. Recovery requires a consecutive stable window. One successful request is
   not sufficient.
5. A random per-run challenge is required by both target and control sentinel.
   Reports carry the challenge hash, never the raw challenge.
6. The Ed25519 signature proves integrity relative to the embedded public key.
   It is not a trusted organizational identity unless the public-key hash is
   independently pinned.
7. Evidence includes raw probe samples, k6 summary, certificate-generation
   events, container logs/inspect/events, command ledger and file hashes.
   A narrative diagnosis is not evidence.

## SLI, SLO, MTTR and blast radius

- Availability is measured from strict TLS probe samples. The pre-fault baseline
  and post-fix recovery windows must each meet the scenario availability SLO.
  The intentionally injected fault window is reported separately.
- Latency p95/p99 comes from k6 HTTP request-duration metrics and is checked
  against the scenario SLO as a hard gate.
- MTTR is stability-confirmed recovery time: from the fault-injected event to
  the end of the first consecutive healthy window that meets min_stable_seconds
  and max_probe_gap_seconds.
- Blast radius is collateral impact: the faulted TLS target is the planned
  scope; the independent control sentinel is the collateral boundary. Any
  failed sentinel probe fails the assertion and zeroes the blast-radius score.
- Container restart counts are captured separately and incur explicit score
  penalties. Recovery over 60 seconds has an additional penalty.

## Security boundary

This lab creates an invalid certificate only inside an ephemeral Docker
Compose project. Host ports are loopback-only. It never modifies OLA's
production runtime, main database, production secrets, Stripe or customer data.
Do not point it at a real service.

## Migration v0 to v1

- Freeze the v0 schema and publish its SHA-256 with each report.
- Add a schema registry and explicit compatibility policy; never reinterpret v0 reports.
- Add typed plugin contracts for fault injectors, probes, traffic engines and
  evidence exporters. Each plugin declares inputs, output schema, capabilities
  and cleanup behavior.
- Make plugin availability explicit: a catalogued fault is not executable
  until a compatible runner plugin exists and passes its own contract tests.
- Generate Compose/Kubernetes manifests, run plans and assertion bundles from
  validated DSL.
- Add JSON Schema migration tooling (v0 to v1) with valid, invalid and
  unknown-field fixtures.
- Preserve v0 verification indefinitely; v1 must not silently re-score v0 evidence.
