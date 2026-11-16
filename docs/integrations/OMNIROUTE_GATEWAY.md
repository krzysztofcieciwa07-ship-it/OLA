# OmniRoute gateway integration (staged)

**Status:** adapter implemented on a feature branch; gateway installation and live-provider acceptance are pending.
**Pinned upstream release:** OmniRoute `v3.8.53`
**Upstream tag object:** `599a2d832522badb1ee74b101caf966f131e8024`
**Upstream release commit:** `191dce8d534ceb56c28a08e71381284a9a87838f` (GitHub signature verified)
**Tag status:** annotated tag object is unsigned; do not treat the tag as a signed provenance statement.
**Windows installer:** `OmniRoute.Setup.3.8.53.exe`
**Expected SHA-256:** `757bc68dff73e9680d18fe1d2d1a8ad3b78318de5948c8218bf02a46ea69ccfe`

## Decision

Use OmniRoute as an optional, separately operated OpenAI-compatible inference gateway. OLA remains the system of record for agent policy, tenant isolation, execution safety, evidence, replay and IGOR verification. OmniRoute does not become an agent executor and does not receive OLA database credentials.

The adapter uses OmniRoute's `POST /v1/responses` endpoint. Upstream source includes a dedicated Responses route that delegates to the shared chat handler. OLA records the provider as `omniroute`, preserving the gateway's model ID and response ID in its existing invocation provenance.

## OLA configuration

Set these values only in the OLA runtime's secret/configuration store (never commit actual values):

```dotenv
OLA_LLM_MODE=required
OLA_LLM_PROVIDER=omniroute
OLA_LLM_MODEL=auto/coding
OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1
OMNIROUTE_API_KEY=<dedicated-OmniRoute-client-key>
```

For a remote gateway, use HTTPS and explicitly allowlist only its hostname:

```dotenv
OMNIROUTE_BASE_URL=https://gateway.example.internal/v1
OLA_OMNIROUTE_ALLOWED_HOSTS=gateway.example.internal
```

The adapter rejects:
- remote plain HTTP;
- HTTPS hosts not present in `OLA_OMNIROUTE_ALLOWED_HOSTS`;
- URL user-info, query strings and fragments;
- base URLs that do not end in `/v1`;
- missing gateway API key or model ID.

Loopback HTTP is accepted only for a local gateway. The adapter never reads or forwards OLA's OpenAI key when `OLA_LLM_PROVIDER=omniroute`.

## Windows download and integrity verification

Run the repository script on the Windows workstation:

```powershell
powershell -NoProfile -File .\scripts\windows\Get-OmniRoute.ps1
```

It downloads the pinned official GitHub release asset and verifies the SHA-256 before keeping the file. The release commit is signed, but the annotated tag itself is unsigned and the release notes report a failed/cancelled `unit-6` Release-Green check on the exact release head. Therefore v3.8.53 is a staging candidate, not production-approved. The optional install path additionally requires a valid Authenticode signature and explicit operator confirmation; verify the signer identity before approving it. It does not install or launch the executable by default. After reviewing the downloaded artifact, an operator may explicitly run:

```powershell
powershell -NoProfile -File .\scripts\windows\Get-OmniRoute.ps1 -Install
```

Official release: https://github.com/cheaper-inference/OmniRoute/releases/tag/v3.8.53

## Gateway hardening requirements

1. Generate unique `JWT_SECRET` and `API_KEY_SECRET`; configure `STORAGE_ENCRYPTION_KEY` so credentials are encrypted at rest. Do not use the public `CHANGEME` initial-password template.
2. Complete first-run setup and change the dashboard password.
3. Keep the dashboard and API bound to loopback for the initial OLA integration. Do not expose port `20128` to the LAN or Internet.
4. Create a dedicated client API key for OLA. Do not give it management/admin access. Confirm its effective scopes and that client API key enforcement is enabled before use.
5. Do not enable or expose OmniRoute MCP for this integration. The upstream MCP documentation states that tool-scope enforcement is opt-in and defaults off; the OLA adapter needs only the authenticated Responses API.
6. Do not use the upstream Docker `cli` profile for this integration. Its documented Docker socket mount is a host-root trust boundary. If Docker is used later, assess the minimal base profile separately.
7. Do not put provider credentials, gateway keys, request bodies or private prompts in GitHub Actions logs or committed evidence.
8. Keep OLA's own tenant/authz and execution gates authoritative. A successful model response is advisory output, not authorization to execute a tool or approve a payment.

## Acceptance gates

The following must be proven before enabling this provider for production traffic:

- [ ] Downloaded Windows installer SHA-256 matches the pinned digest.
- [ ] Authenticode signature is valid and signer identity is independently confirmed against the publisher's official identity.
- [ ] Release-Green failure/cancelled `unit-6` is investigated or a later release with a complete green release gate is selected.
- [ ] OmniRoute version and build provenance match the pinned release.
- [ ] Dashboard/API listener is loopback-only; no public port is reachable.
- [ ] Unique secrets are configured; storage encryption is enabled; default password is replaced.
- [ ] OLA client key is dedicated and has no management/admin capability.
- [ ] Authenticated `GET /v1/models` and `POST /v1/responses` succeed from the OLA host.
- [ ] OLA receives a real response with `provider=omniroute`, expected model and non-empty response ID.
- [ ] Invalid key, unapproved host, gateway timeout and provider exhaustion all fail closed.
- [ ] NINA planner JSON is parsed and independently schema-validated; malformed output never executes.
- [ ] Evidence contains provider/model/response ID/prompt digest, but no API key or raw secret.
- [ ] Fallback is exercised against at least one controlled provider failure and recorded.
- [ ] IGOR independently verifies the resulting evidence chain.

A passing unit test for the adapter is not a live OmniRoute acceptance test. No production credentials, Railway deployment, production database, or public exposure are part of this staged change.
