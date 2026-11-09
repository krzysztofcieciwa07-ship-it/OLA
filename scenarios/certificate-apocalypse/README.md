# Certificate Apocalypse

An isolated Docker Compose experiment that changes a local TLS service from a
valid leaf certificate to an expired leaf certificate, proves strict client
rejection, restores a valid certificate, and measures recovery stability.

## Prerequisites

- Docker Engine with the Compose v2 plugin.
- Python 3.13+ and OpenSSL 3.x on the host.
- Grafana k6 2.3.0 on the host.
- Install dependencies from the repository root:

    python -m pip install -r requirements.txt -r scenarios/certificate-apocalypse/requirements-chaos.txt

## Run the complete experiment

From the repository root:

    make scenario

The runner creates a fresh per-run challenge, CA and leaf certificate, starts
two loopback-only services, runs strict probes and k6 traffic, serves an
expired certificate, restores a valid certificate, checks a randomized
stability interval, captures Docker evidence, scores the result and signs the
evidence manifest.

Reports are retained under scenarios/certificate-apocalypse/runs/<run-id>/.
The unredacted challenge, certificate private keys and signing private key stay
under the ignored runtime/ directory and are not copied to the report.

## Manual controls

    make up       # create run context and start the isolated services
    make break    # atomically serve a certificate expired in the past
    make probe    # perform one strict TLS + control-sentinel probe
    make fix      # atomically restore a currently valid TLS certificate
    make assert   # validate the most recent complete evidence set
    make score    # calculate score and sign its evidence manifest
    make down     # remove only this Compose project

Use make scenario for the complete timed experiment. Manual break/fix commands
are intentionally not scored without probe samples and the full event ledger.

## Evidence and interpretation

- Availability is calculated from strict probe results, separately for
  baseline, fault and recovery phases.
- Latency p95/p99 comes from k6's HTTP request-duration distribution; strict
  probe latencies are retained as raw evidence.
- MTTR is measured from recorded fault injection to the end of the first
  consecutive healthy window meeting the randomized stability policy.
- Blast radius is collateral impact: the TLS target is the planned fault scope;
  the independent control sentinel is the collateral boundary. Any failed
  control-sentinel probe increases the blast-radius ratio.
- Container restart counts are captured separately.
- A self-generated Ed25519 key gives tamper evidence, not trusted identity.
  Set OLA_EVIDENCE_SIGNING_KEY and independently pin
  OLA_EVIDENCE_TRUSTED_SIGNER_SHA256 for a pinned-key verification status.
  A self-signed local report is not an enterprise certificate.

## Safety

The Compose file binds only to 127.0.0.1 and uses an internal network,
read-only filesystems, dropped Linux capabilities and no-new-privileges.
Do not change the host binding to 0.0.0.0 or reuse the generated certificate
against a public endpoint.
