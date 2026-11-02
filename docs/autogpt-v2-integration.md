# OLA / NINA / IGOR — AutoGPT API v2 bridge

Status: **opt-in / external / unverified / no production authorization**.

NINA can hand an explicitly approved owner task to a pre-existing AutoGPT
library agent. AutoGPT executes externally; IGOR is **not** replaced by that
agent. An AutoGPT `COMPLETED` status does not become OLA `VERIFIED`.

## Source and license

- AutoGPT API v2 documentation: https://agpt.co/docs/platform/api-and-integrations/api-guide
- AutoGPT OpenAPI schema: https://backend.agpt.co/api/v2/openapi.json
- The bridge is OLA-authored HTTP client code using the documented public API;
  no `autogpt_platform/` source is copied. Its source has PolyForm Shield terms
  limiting competitive use. AutoGPT Classic uses MIT, but is not a dependency
  of this bridge.

## Configuration (server only)

| Variable | Purpose |
| --- | --- |
| `OLA_AUTOGPT_ENABLED=1` | Explicit owner opt-in; default disabled |
| `OLA_AUTOGPT_OWNER_TENANT_ID` | The only tenant allowed to dispatch |
| `OLA_AUTOGPT_API_KEY` | AutoGPT v2 key with RUN_AGENT and READ_RUN scopes |
| `OLA_AUTOGPT_AGENT_ID` | Existing library agent ID |
| `OLA_AUTOGPT_INPUT_FIELD` | Exact text input field of that agent; no guessed default |
| `OLA_AUTOGPT_API_URL` | Default `https://backend.agpt.co/api/v2` |
| `OLA_AUTOGPT_ALLOWED_HOSTS` | Default `backend.agpt.co` (comma-separated) |
| `OLA_AUTOGPT_ALLOW_LOCAL_HTTP=1` | Optional localhost-only HTTP for self-host tests |

Store credentials in the deployment's secret manager. Never commit them or
paste them into a chat/task. Do not enable dispatch before a budget, data
handling scope and external-service access are approved.

## Existing API integration

After authentication with an **OLA** API key for the configured owner tenant:

1. `POST /nina-autogpt` with JSON `{"task":"...","operation_id":"<UUID>"}`.
   The UI generates the UUID for each explicitly confirmed action.
2. OLA checks its evidence chain and idempotency history. It writes a server-
   bound `integration.autogpt.requested` event **before** remote dispatch.
3. The adapter calls AutoGPT v2's
   `POST /library/agents/{agent_id}/runs` with `Idempotency-Key` and gets `202`.
4. OLA records `integration.autogpt.accepted`, returning the remote run ID.
5. `GET /nina-autogpt/{run_id}` reads that tenant's accepted run via
   AutoGPT v2's `GET /runs/{run_id}`. No remote output is granted trusted
   execution provenance by polling.

If remote execution may have started but no receipt is safely recorded, OLA
blocks retries of that operation ID and requires manual reconciliation. Do not
invent a new operation ID to force a retry: that could create a second paid run.

## Safety properties and limitations

- `OLA_AUTOGPT_ENABLED` is **off by default**.
- Only the explicitly configured owner tenant can start or inspect runs.
- The browser never receives the AutoGPT API key.
- TLS origin allowlist, blocked redirects, response-size limit, timeout and
  bounded input protect the HTTP boundary.
- Public tenant evidence cannot forge `integration.autogpt.*` records.
- Evidence stores task SHA-256, operation/run IDs and remote status, **not**
  raw task text or AutoGPT credentials.
- `EXTERNAL_PENDING_UNVERIFIED` / `EXTERNAL_OBSERVED_UNVERIFIED` mean that
  the remote service reported a state. They do **not** authorize an external
  action on behalf of OLA or a production release.
- There is no live external end-to-end proof until real owner credentials,
  a library agent, cost controls and an independent IGOR verification policy
  have been configured and tested.

## Tests

`python -m pytest -q tests/test_autogpt_v2_bridge.py tests/test_team_dashboard.py`

Tests mock AutoGPT's HTTP responses; no paid external execution is performed.
