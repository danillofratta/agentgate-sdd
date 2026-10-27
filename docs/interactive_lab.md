# Interactive lab — Milestones A, B and C

This local simulation adds PostgreSQL and a browser to the authorization harness.
Milestone B adds a real authenticated MCP server calling the same FastAPI API.
Milestone C adds optional conversational AI through the real MCP client boundary.
No real funds or external execution tools are involved. A provider key enables
billable model requests; without it, chat is disabled and the manual lab works.
The single OpenSpec change `add-interactive-lab` tracks all three milestones.

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

## Guided operations console

The redesign is tracked separately in `redesign-interactive-lab-ux`; the existing
`add-interactive-lab` change remains unchanged. Dashboard shows balances and recent
resume links. AI Assistant and Operations share one authoritative operation panel.
Developer Inspector is collapsed by default, with sanitized HTTP/MCP/audit evidence.

1. Choose **Ask the assistant** or **Create manually**. Manual amounts use USD,
   converted exactly to integer cents. A submitted request remains immutable.
2. Propose **$1 · Allowed**. Status is **Authorized — not executed**. Choose
   **Execute operation** explicitly, then **Replay safely** to retrieve its stored
   result without another debit. Inspect current balances on Dashboard.
3. Choose **New operation**, propose **$100.01 · Needs approval**, then **Review
   request**. Review the exact amount, accounts, original policy and deadline as
   the separate synthetic human. Check the confirmation and **Confirm approval**.
   Status becomes **Approved — awaiting execution**; balances remain unchanged.
   Choose **Execute approved transfer** separately.
4. Reject another request in the review dialog. Propose **$1,000.01 · Denied**.
   Neither offers execution. Presets remain subject to available funds/permissions.
5. Expand **Audit timeline**, page through evidence and open **Developer Inspector**
   when needed. Original policy remains unchanged after human approval/execution.
6. Navigate between Assistant and Operations, then reload or resume by saved ID.
   Recent rows cover this browser and loaded audit pages, not a complete global list.
7. On uncertain manual submission, **Reconcile original request** explicitly reuses
   the retained key/payload, including after reload. No financial action retries
   automatically. The recovery banner stays available in every view. Known
   original operation IDs reconcile through a read-only query. An unrelated ID
   or chat response never unlocks uncertainty.
8. A rejected CSRF token renews the session without resending the mutation or
   removing original recovery data. Choose the original recovery action again.
   Browser recovery storage must work before financial mutations are sent.
9. Audit outages affect only the evidence view. **Retry audit retrieval** retries
   reads independently; confirmed operations can still continue. Failed saved-ID
   restoration remains visible in Operations instead of showing a readiness message.

If an unconfirmed chat call loses its session before any original operation ID is
known, the existing backend contracts cannot reconstruct its server-side key.
The console retains a blocked recovery record and explains the missing original
reference/context. Loading an unrelated operation cannot unlock it. Chat messages
and credentials are never persisted by the recovery mechanism.

See [UX verification and manual acceptance](interactive_lab_ux_acceptance.md) for
recorded checks, remaining browser checks and frontend-only rebuild commands.

The human buttons represent a separate synthetic approver in a single-user
teaching interface, not production login or multi-user authorization. Host and
Origin checks, fetch metadata and session-bound CSRF prevent cross-site use.
The proxy has only fixed API methods/destinations; browser identity, URL, policy
or authorization overrides are never trusted. The model never receives
these credentials or human approval controls as agent tools.

## MCP server and official SDK client

AI chat configuration and usage are documented below; the manual MCP client is
also useful for inspecting persisted operations after losing chat memory.

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

## AI chat provider configuration

The existing frontend process hosts the server-side agent; no additional port is
published. Its agent handler receives only a model gateway, MCP credential and
bounded chat-memory port. The independent manual human controls continue to use
their separate approver identity. No authentication settings, database, arbitrary
HTTP tool, filesystem or approval tool are exposed to the model.

Run startup once to create the ignored `.lab-secrets/llm_api_key` file, initially
empty. Empty/missing keys, invalid configuration and missing model names disable
chat without breaking manual actions or Swagger. Configure a real provider only
when you intend to send conversation data and pay for the resulting requests.
Use an account credential limited to synthetic lab usage, with a spending limit.

For Docker, enter the provider key into that local file without placing it in
command history (PowerShell 7):

```powershell
$providerKey = Read-Host 'Provider API key' -MaskInput
[System.IO.File]::WriteAllText((Join-Path (Get-Location) '.lab-secrets/llm_api_key'), $providerKey)
Remove-Variable providerKey
$env:AGENTGATE_LLM_PROVIDER = 'openai' # or groq
$env:AGENTGATE_LLM_MODEL = Read-Host 'Tool-capable model ID from your provider account'
.\scripts\start_lab.ps1
```

Do not commit the secret, put it in Compose YAML, screenshots or browser inputs,
or print environment/Compose secret contents. The existing ignored secret
directory has restricted local access; Compose mounts the key read-only. Direct
non-Docker startup can use `AGENTGATE_LLM_API_KEY` or its `_FILE` variant. File
configuration takes precedence. The agent never exports these values to chat.

| Variable | Default / allowed range |
| --- | --- |
| `AGENTGATE_LLM_PROVIDER` | `openai` or `groq` |
| `AGENTGATE_LLM_BASE_URL` | Derived: `https://api.openai.com/v1` or `https://api.groq.com/openai/v1`; only the matching provider origin is accepted |
| `AGENTGATE_LLM_MODEL` | Required; choose a Chat Completions function-capable model from your account; no hardcoded model fallback |
| `AGENTGATE_LLM_API_KEY`, `AGENTGATE_LLM_API_KEY_FILE` | Required for chat; Compose uses `/run/secrets/llm_api_key` |
| `AGENTGATE_LLM_TIMEOUT` | 20 seconds; 1–60, per provider request |
| `AGENTGATE_LLM_MAX_TOKENS` | 512; 64–4,096 completion tokens |
| `AGENTGATE_LLM_MAX_TOOL_CALLS` | 6; 1–12 model-requested calls per turn |
| `AGENTGATE_LLM_MAX_HISTORY` | 12; 2–24 previous/current user/assistant messages |
| `AGENTGATE_CHAT_MCP_URL` | Internal `http://mcp:8000/mcp`; direct host tests may use `http://127.0.0.1:8002/mcp` |

The first chat turn performs one harmless forced function call to verify the
selected model supports the configured wire contract. This costs a small extra
request once per process; it has no business effect. Provider rejection, quota,
unsupported tools, truncated output and timeout fail closed with sanitized errors.
Choose sufficient output tokens for your model's reasoning plus tool response.
No model or provider is assumed to be verified merely because it is configured.

Try the five suggested prompts: Alice's balance, $1 transfer, $100.01 transfer,
$1,000.01 transfer and last-operation status. The agent discovers exactly the
three existing MCP tools, validates proposed arguments, supplies its own stable
key and returns real results to the model. Balance reads may execute immediately.
For transfers, follow the single verified operation panel: **Review request**,
confirm independently, then **Execute approved transfer**. Allowed requests offer
**Execute operation**. Chat-associated execution retains MCP; recovered operations
without chat association use the existing manual API harness route.
Approval and execution confirmation are separate; typing either into chat cannot
authorize them. Denial is final under the existing policy. Replay uses the same
persisted operation ID. Audit remains available in the existing dashboard.

The timeline shows sanitized discovered tools, real invocations, HTTP status,
operation ID and policy state. Collapsible details contain validated MCP data.
Assistant text is labeled unverified and can be wrong even when persisted state is
correct. Safe inline bold/code formatting uses text nodes without HTML injection,
with the existing restrictive CSP and CSRF boundary.

If I/O becomes uncertain, use **Resume original call**. A live server session
retains the original payload and key, and blocks fresh proposals until recovery.
There is no automatic financial retry with a new key. Chat sessions expire after
one idle hour and are capped at 64 sessions, 32 operation cards and one active
turn per session. Frontend restart clears chat memory; PostgreSQL retains business
state. Keep operation IDs and use **Resume an existing operation** in the manual
dashboard after restart. Inspect uncertain state before making another proposal.

See [Milestone C verification](milestone_c_verification.md) for concrete offline,
Docker/browser evidence and the separately opt-in billable provider smoke. The
reported manual Groq demonstration is user-reported evidence; offline mocked
provider tests and deterministic browser checks do not establish live provider
interoperability. No real-provider smoke was run during portfolio finalization.
Real provider data retention and costs depend on your account.

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

Redesign verification is recorded in [the UX checklist](interactive_lab_ux_acceptance.md).
Run dependency-free frontend behavior checks with
`node --test tests/frontend/console.test.cjs`. These also run in the quality CI job.
The updated browser scripts below are optional and were not executed for this
redesign. A new browser session/reload clears chat association; persisted IDs remain
recoverable. After CSRF rejection the console renews the session and requires an
explicit repeat action; it never silently resends the rejected mutation.

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
