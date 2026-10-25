# Interactive lab — Milestones A and B

This local simulation adds PostgreSQL and a browser to the authorization harness.
Milestone B adds a real authenticated MCP server calling the same FastAPI API.
No real funds, LLM provider or external execution tools are involved. The single
OpenSpec change `add-interactive-lab` tracks A, B and C; C remains unimplemented.

## Windows startup

Install Docker Desktop with Linux containers and Compose v2. From the repository
root, run this single command in Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_lab.ps1
```

- Frontend: <http://127.0.0.1:8080>
- Swagger: <http://127.0.0.1:8001/docs>
- OpenAPI: <http://127.0.0.1:8001/openapi.json>
- MCP Streamable HTTP: <http://127.0.0.1:8002/mcp>

Port 8001 avoids an existing service on 8000; internal API traffic uses 8000.
Keep 8080, 8001 and 8002 free. Build downloads images and packages; runtime tools are
local. The API, frontend and MCP run as an unprivileged container user. Only their
IPv4 loopback ports are published. PostgreSQL has no published port and uses an
internal persistence network. The lab network permits Docker host forwarding;
it exposes no generic outbound proxy or remote tools.

The script generates four independent random secrets into ignored `.lab-secrets`
files, restricts that directory to the current Windows identity and mounts the
files read-only through Compose secrets. No token is printed, committed or
embedded in images or browser assets. Retain these files with the data volume.
Docker administrators can access container secrets. Swagger does not inject
credentials; use the browser lab for the credential-free demonstration.
`AGENTGATE_LOCAL_DEVELOPMENT=1` explicitly enables Swagger and `/accounts`;
the default API surface remains unchanged and documentation stays disabled.

## Demonstrate business behavior

1. Observe Alice and Bob balances ($10,000 each on first startup).
2. Select `$1 · Allow`, submit, then Execute. Replay returns the stored result
   without another transfer.
3. Select `$200 · Approval`, submit and observe `REQUIRE_APPROVAL` and
   `PENDING_APPROVAL`. Human Approve grants the exact operation; Execute returns
   `SUCCEEDED` with effective `ALLOW / HUMAN_APPROVED`. Original policy stays
   `REQUIRE_APPROVAL`.
4. Submit another pending operation with a new key and Reject. State becomes
   `REJECTED`; execution is blocked and balances stay unchanged.
5. Select `$1,000.01 · Deny`; observe DENY and unchanged balances.
6. Inspect status, approval expiry, paginated audit timeline and the HTTP
   inspector. It shows the last action's request/status/body, excluding bearer
   headers and CSRF values. Uncheck Current operation to see other records.
7. Reuse the same key and intent to replay submission. Changed arguments under
   the same key return 409. Generate new creates a fresh intent. Resume an
   operation by ID after restarting.
8. `get_balance` is a separately submitted and executed local tool. Balance
   cards use the approver-only read-only query, adding no audit/operation noise.
   Agent source permissions remain Alice-only. Approval expires in 300 seconds.

The human buttons represent a separate synthetic approver in a single-user
teaching interface, not production login or multi-user authorization. Host and
Origin checks, fetch metadata and session-bound CSRF prevent cross-site use.
The proxy has only fixed API methods/destinations; browser identity, URL, policy
or authorization overrides are never trusted. A future model must not receive
these credentials or human approval controls as agent tools.

## MCP server and official SDK client

Compose's `mcp` service uses the official patched `mcp==2.3.0` Python SDK. It forwards
fixed HTTP calls to `http://api:8000`; MCP has no persistence network, database
credential, approval credential or direct tool dispatch capability. API health
is a startup dependency. `/health` indicates that the MCP application/lifespan
is ready; it does not promise that the upstream API remains available.

| MCP tool | Arguments | Existing HTTP endpoint |
| --- | --- | --- |
| `request_operation` | `tool_name`, structured `arguments`, `idempotency_key` | `POST /operations` |
| `get_operation` | `operation_id` | `GET /operations/{id}` |
| `execute_operation` | `operation_id` | `POST /operations/{id}/execute`, empty body |

`tool_name` is `get_balance` or `simulate_transfer`, with the same strict
arguments as HTTP. Extra fields, role/principal overrides and replacement
execution arguments are rejected. Submission never executes. Human approval
uses the independent frontend/API workflow; it is absent from MCP discovery.
Results contain `http_status` and the actual API operation fields (`id`, `state`,
`decision`, `reason`, and result; inspection includes approval metadata).
Tool failures set MCP `isError` and return a fixed sanitized error code.
No application-level automatic retries occur after connection failures/timeouts;
reuse the original key/ID to reconcile against the persisted API state.

Inbound MCP uses `.lab-secrets/mcp_token`, independently generated from
`.lab-secrets/agent_token`. Only the latter is used for upstream API calls.
Clients never receive the upstream credential. All MCP clients share the same
synthetic AgentGate agent identity, with its existing Alice source permission;
this static local demo is **not a production multi-user OAuth authorization
system**. It has no OAuth discovery or token delegation. Do not distribute the
secret files or expose these services beyond the trusted local host.

```powershell
uv run --locked python scripts/mcp_client.py list
uv run --locked python scripts/mcp_client.py request_operation '{"tool_name":"get_balance","arguments":{"account_id":"acct-alice"},"idempotency_key":"mcp-balance-demo"}'
# Replace the UUID with the returned id; execution stays explicit:
uv run --locked python scripts/mcp_client.py get_operation '{"operation_id":"00000000-0000-4000-8000-000000000001"}'
uv run --locked python scripts/mcp_client.py execute_operation '{"operation_id":"00000000-0000-4000-8000-000000000001"}'
```

The client reads only the MCP credential, without printing it. The script uses
the SDK v2 legacy compatibility mode to demonstrate a real initialization
handshake over Streamable HTTP. Tests and smoke verification also exercise
v2 automatic modern negotiation. No legacy SSE endpoint is exposed. The ASGI
factory enters the SDK lifespan once and closes its shared HTTP client on
shutdown. Stateless HTTP means sessions are not an authorization or replay
store; PostgreSQL remains authoritative.

Exact allowed Hosts are `127.0.0.1:8002`, `localhost:8002` and container-local
`127.0.0.1:8000` (health check). Optional Origin must exactly match
`http://127.0.0.1:8002` or `http://localhost:8002`; absent Origin supports native
clients. Duplicate Host/Origin/Authorization and cross-site fetches are rejected.
The SDK also has DNS rebinding protection enabled. Bodies are limited to 16 KiB,
including streamed bytes. Internal HTTP has a one-second connect timeout and
four-second connect/read/write/pool limits, no redirects and no environment
proxy inheritance. These I/O limits do not change the harness's two-second
execution budget. Access logging is disabled; rejected arguments, headers and
exception details are not returned or logged by the adapter.

MCP is opt-in via `AGENTGATE_MCP_ENABLED=1` in its separate container; the default
API does not mount MCP. Re-running startup reuses all existing secrets and
storage, adding only a missing MCP token for an existing A installation.

## Persistence and recovery

`AGENTGATE_DATABASE` remains a SQLite path by default and accepts an explicit
`postgresql://` or `postgres://` URL. Compose uses PostgreSQL host/password-file
configuration instead of putting its password in a URL environment variable.
`dependencies.py` chooses all adapters. Six existing repository contracts and
the Unit of Work remain the application boundary. Shared hydration functions
are pure; SQL and parameter binding remain in backend adapters. PostgreSQL
schema v1 includes all current SQLite v6 fields. No automatic data copy occurs.

Command transactions use READ COMMITTED and a transaction-scoped advisory
writer lock before authoritative reads. All application writers participate,
including submission, approval, attempt allocation and recovery. This deliberate
coarse serialization matches SQLite behavior and trades throughput for simple
auditable correctness. Direct SQL writers are outside this application protocol.
Read adapters use REPEATABLE READ READ ONLY snapshots without the writer lock.

Only the UoW commits. Balances, result, approval consumption and success audit
commit together. Attempt evidence commits before dispatch. Each repository
statement refreshes its timeout against the same execution deadline. Only
classified transient locks with proven rollback retry. Entered commit failures
remain uncertain and require fresh durable reconciliation before redispatch.
Connection establishment and entered COMMIT are not hard real-time interruptible.

The named `postgres_data` volume survives stop/start, restart, rebuild and
ordinary `docker compose down`. Seeding inserts missing accounts and never
updates existing balances. Retain both volume and secrets, and back them up
before maintenance. Losing the PostgreSQL password file requires deliberate
administrator recovery: silently generating another password cannot change the
password stored in an existing database.

```powershell
docker compose stop
docker compose up -d --wait
docker compose down   # retains named data volume
```

## Verification

```powershell
uv sync --locked --python 3.12
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy --strict src
openspec validate --all --strict
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
uv run --locked python scripts/smoke_lab.py
uv run --locked python scripts/smoke_mcp.py
# Optional UI QA using installed Microsoft Edge:
uv run --locked --with playwright==1.56.0 python scripts/browser_smoke.py
```

Default tests remain offline with outbound network/subprocesses blocked. Opt-in
integration tests run in a separate Compose project, on an internal network and
tmpfs PostgreSQL database. Their fixture only accepts `postgres-test` and
`agentgate_test` and blocks subprocesses. They never reset the persistent lab.
Isolation/read-only, duplicate/distinct concurrency, conservation, approval,
audit rollback, restart replay, uncertain commits, connection loss, deadline,
ownership and malicious input have independent integration cases.

The smoke script creates simulation records and transfers $201 from Alice to
Bob, then restarts PostgreSQL and API containers and checks balances, approval,
idempotency and one committed success. Repeated runs use fresh keys. It reads
no credential files and never deletes a volume. It runs outside offline Pytest.

Browser QA also creates simulation records and transfers $201. It uses installed
Edge, checks desktop and 390px mobile layouts and saves screenshots to ignored
`.lab-artifacts`. Playwright is not an application/runtime dependency. CI now
defines separate jobs for offline quality gates and real PostgreSQL/Docker smoke;
the remote jobs will first run when the changes are pushed or proposed.

The locking design follows
[PostgreSQL advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)
and [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
See [recorded verification](milestone_a_verification.md) for results and limits.
See [Milestone B verification](milestone_b_verification.md) for MCP evidence.

The MCP smoke uses the real SDK over host loopback, verifies PostgreSQL with
read-only `docker compose exec ... psql` queries outside the MCP process, and
restarts only API/MCP for durable replay. It creates operations and transfers
20,100 synthetic cents per run; it never resets data. The separate human
frontend workflow grants approval. Run it on a trusted local demo with enough
Alice balance and no concurrent manual changes. Container logs and the client
must never be configured to print secret headers or bodies.
