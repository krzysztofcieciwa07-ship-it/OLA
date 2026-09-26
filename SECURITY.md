# Security Policy

## Python Dependency and License Policy

OLA is a Python/FastAPI application. Python dependencies are declared through
supported project manifests such as `requirements.txt` and, if introduced,
`pyproject.toml`.

Every Python dependency is subject to CI review. The CI policy gate:

- blocks dependencies whose reported license contains GPL or AGPL;
- audits declared Python dependencies for known published vulnerabilities;
- produces a machine-readable dependency/license inventory as a CI artifact;
- must be updated deliberately if the project changes its dependency-management
  format.

A dependency is not considered "safe" merely because it is absent from a
direct manifest: transitive dependencies are included in the installed
environment audit. License metadata is evidence for review, not a substitute
for legal/compliance judgment where a package reports an ambiguous or
multi-license expression.

The policy is fail-closed for detected GPL/AGPL licenses and for failed
vulnerability audits. If the repository has no Python dependency manifest,
the policy job records that fact and does not invent a dependency result.

## Supported Versions

Use this section to tell people about which versions of your project are
currently being supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 5.1.x   | :white_check_mark: |
| 5.0.x   | :x:                |
| 4.0.x   | :white_check_mark: |
| < 4.0   | :x:                |

## Reporting a Vulnerability

Use this section to tell people how to report a vulnerability.

Tell them where to go, how often they can expect to get an update on a
reported vulnerability, what to expect if the vulnerability is accepted or
declined, etc.
