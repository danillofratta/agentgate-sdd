# Milestone B verification — real MCP server

Verified 2026-10-24, America/Sao_Paulo. Milestone B is complete under
`add-interactive-lab`; A's requirements remain complete and C is unimplemented.
No branch, commit, push or archive was created.

The endpoint is **http://127.0.0.1:8002/mcp**. The official Python SDK is pinned
to patched `mcp==2.3.0` in `pyproject.toml` and `uv.lock`. This is the official SDK,
not the separately distributed FastMCP package. The implementation uses its
public `mcp.server.Server` callback API and `streamable_http_app`, with managed
lifespan, stateless JSON responses and a 16 KiB request limit. The real client
uses `mcp.client.Client` and the SDK's Streamable HTTP transport. Legacy-mode
initialization compatibility and v2 automatic negotiation were both exercised;
no legacy SSE endpoint or subprocess transport is provided.

SDK references: [official v2 documentation](https://py.sdk.modelcontextprotocol.io/),
[migration and transport lifecycle](https://py.sdk.modelcontextprotocol.io/migration/).
Startup, authentication and invocation examples are in
[the lab guide](interactive_lab.md#mcp-server-and-official-sdk-client).

## SDK security update

The pre-commit security review upgraded `mcp==2.0.0` to **`mcp==2.3.0`** and
regenerated `uv.lock`; `mcp-types` is also 2.3.0. The existing locked
`httpx2==2.16.0` satisfies the SDK's raised minimum of 2.10.0. No production
Python code or business behavior needed a compatibility change. See the
[official 2.3.0 release notes](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0).

[CVE-2026-59951 / GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv)
affects stateful Streamable HTTP in MCP 2.0.0 through 2.1.1; the 2.x fix starts
at 2.2.0. The advisory explicitly excludes servers using `stateless_http=True`,
which AgentGate already configured before this update. Authentication alone
would not bound sessions created by a token holder in vulnerable stateful mode.

The transport audit confirmed `stateless_http=True`, `json_response=True`, a
16 KiB body limit, no event store and one managed SDK lifespan. The installed
2.3.0 manager creates a transport without a session ID for each legacy HTTP
request and terminates it in `finally`, including cancellation. Its stateful
limits default to 1800 seconds idle and 10000 sessions; these finite defaults
were not disabled, but are unused in AgentGate's stateless mode. There is no
persistent MCP session or retained initialization store to expire. PostgreSQL
continues to own business state and replay. SDK shutdown cancels managed tasks,
and the surrounding lifespan closes the shared upstream HTTP client.

A new offline security regression performs eight real initialization requests,
checks that none returns `Mcp-Session-Id`, discovers all three tools without a
session ID and checks that the upstream client closes on lifespan exit. The
test bounds the complete lifecycle with a five-second test timeout; this is
not a new application execution deadline. Existing authentication, exact
Host/Origin validation, SDK DNS rebinding protection, I/O timeouts, sanitized
errors and loopback-only Compose exposure remain unchanged.

The rebuilt running MCP container reported `mcp==2.3.0` and
`mcp-types==2.3.0`. Eight additional initialization requests against the actual
Docker endpoint also returned no session identifier. The standalone
`scripts/mcp_client.py list` discovered exactly the three business tools.
All upgrade verification completed without a compatibility failure. This
security update changes the dependency/lockfile, the session lifecycle
regression test, this report, the lab guide, the quality-gate report link and
the existing OpenSpec design's SDK version; it adds no production code changes
or Milestone C behavior.

## Quality gates

| Verification | Final result |
| --- | --- |
| `uv sync --locked --python 3.12` | Passed, 50 resolved packages |
| `uv run --locked pytest` | **982 passed**, 32.82 seconds; all original 943 plus 39 MCP cases |
| `uv run --locked ruff check .` | Passed |
| `uv run --locked ruff format --check .` | Passed, 279 Python files |
| `uv run --locked mypy --strict src` | Passed, 183 source files |
| `openspec validate --all --strict` | Passed, both active changes |
| Disposable PostgreSQL Compose suite | **17 passed**, 4.28 seconds; original 16 plus one MCP concurrency case |
| Original `scripts/smoke_lab.py` | Passed, including frontend/Swagger, human rejection and PostgreSQL/API restart |
| Real `scripts/smoke_mcp.py` | Passed, including real protocol, SQL evidence and API/MCP restart |
| Standalone `scripts/mcp_client.py list` | Passed against rebuilt SDK 2.3.0 container; exactly three tools |
| Repeated initialization at actual Docker endpoint | Passed; eight responses without `Mcp-Session-Id` |
| Generated-secret scan of API/MCP/frontend logs | Passed; compared in memory without printing secrets |
| `git diff --check` | Passed |

Host: Windows, Python 3.12.14, uv 0.12.5. Docker: Linux containers,
Python 3.12.15, PostgreSQL 16.15. CI now runs the MCP smoke after the original
lab smoke and creates the additional ephemeral credential. Remote CI has not
run because this increment creates no push or Pull Request.

The default suite remains offline: real SDK framing over HTTP ASGI transports
reaches the existing FastAPI handlers and temporary SQLite database without
network sockets or subprocesses. Fake transport tests cover upstream failures;
protocol behavior is not mocked. The disposable integration uses the same
SDK/HTTP boundary and actual PostgreSQL. The Docker smoke uses the actual
published MCP endpoint and running API/database containers.

During development an initial offline concurrent replay case using the real
clock returned a sanitized 503 under build/test load. The new fixture now
injects the existing FakeClock, as required for offline tests. No production
deadline, SQLite wait budget or financial assertion was relaxed. Final full
regression, disposable PostgreSQL concurrency and real Docker concurrency all
passed. An initial integration helper import also failed in the container;
the integration test is now self-contained.

## Real client and PostgreSQL results

The final smoke verified:

1. Real SDK initialization, discovery of exactly `request_operation`,
   `get_operation`, `execute_operation`, and actual invocation.
2. A 100-cent ALLOW submission remains unexecuted until explicit execution;
   a 100001-cent DENY submission cannot execute.
3. Four concurrent identical 20000-cent submissions return one 201 and three
   200 responses, all referring to one REQUIRE_APPROVAL operation.
4. Execution before approval returns 409. Approval-tool calls, role/principal
   overrides, replacement execution arguments, boolean amounts and changed
   idempotent intent are rejected without changing that operation's SQL state.
5. The independent existing browser proxy grants approval with its own
   server-held human credential and session CSRF. The MCP client never reads
   an approver or AgentGate agent token.
6. Four concurrent MCP executions return the same SUCCEEDED result with
   effective HUMAN_APPROVED authorization. SQL contains one success audit.
7. Inspection returns the actual persisted arguments and CONSUMED approval.
   Read-only SQL verifies owner, key, canonical request, fingerprint, policy,
   original decision/reason, timestamps and approval expiry are unchanged.
   Approval fingerprint/policy/owner match the request; the recorded approver
   remains `principal-approver`.
8. SDK modern automatic negotiation also discovers tools and replays that
   result. Unauthenticated SDK initialization fails; unauthorized calls and
   hostile Host/Origin requests return 401/403.
9. After API and MCP container restart and health recovery, submission and
   execution replay return the same ID/result. Complete operation/approval
   SQL snapshots, success count and balances remain identical.

Final verified MCP operation: `79995443-94a1-453c-b92b-8c7e7620fc33`.
Before the final MCP smoke, Alice/Bob held 839200/1160800 cents; afterward they
held **819100/1180900** cents. Total remained **2000000** cents. These are
existing persistent demo balances, not freshly reset seed values. Each smoke
run transfers 20100 synthetic cents and uses fresh keys. Earlier verification
records are retained. SQL is used only by the separate verification script,
never by MCP tools or their process.

The original final A smoke also passed, including independent grant/reject,
frontend protection, Swagger, execution/replay and PostgreSQL/API restart.
Final Compose health checks pass for all four services. PostgreSQL has no
published port; MCP/API/frontend publish only host IPv4 loopback.

## Security evidence and limits

MCP mounts only `mcp_token` and `agent_token`; it has no approver/password mount
or persistence network. The generated inbound token differs from the API agent
token; missing, weak or reused credentials fail startup. Tools receive no
identity, approver, authorization, URL or policy override parameter. The API
continues to enforce ownership, policy, immutable approval, expiration, execution
deadlines, atomic persistence and durable replay through its existing handlers
and harness. No business policy or direct dispatch was added to transport.

Tests verify exact schemas/discovery, both SDK negotiation modes, ALLOW/DENY,
approval protection, principal isolation with concealed 404 and unchanged SQL,
idempotency conflict, concurrent/restart replay, strict input rejection, Host/
Origin/authentication rejection, streamed size limits, malformed-envelope
sanitization, health, connection errors, timeouts and invalid/upstream failures.
The runtime rejects duplicate security headers and enables the SDK's additional
DNS rebinding protection. API calls use explicit timeouts, no redirects/proxies
and an empty execution body. SDK validation errors are not echoed with rejected
arguments. Credentials and exception text were absent from observed responses
and captured service logs.

No unresolved implementation blocker remains. This is a trusted-host,
single-agent static credential demo, **not production multi-user OAuth**.
Any holder of its MCP token has the configured agent's permissions. Local
processes/Docker administrators remain trusted; production TLS, OAuth, rotation,
rate limiting, availability and performance guarantees remain outside scope.
Readiness proves the MCP lifespan is running; upstream failure returns a
sanitized unavailable result. HTTP I/O timeouts are not hard total wall-clock
or transaction cancellation guarantees. Reconcile lost responses with the
original operation ID/key. The existing harness's guarantees and limits remain
unchanged. Milestone C/LLM/chat was not implemented.

## Files changed

| Area | Files |
| --- | --- |
| SDK and composition | `pyproject.toml`, `uv.lock`, `src/agentgate/mcp.py`, `src/agentgate/dependencies.py`, `src/agentgate/infrastructure/security/settings.py` |
| MCP adapter | `src/agentgate/application/ports/mcp_api_gateway.py`, `src/agentgate/infrastructure/gateways/local_mcp_api_gateway.py`, `src/agentgate/features/mcp_ingress/__init__.py`, `src/agentgate/features/mcp_ingress/endpoint.py`, `src/agentgate/features/mcp_ingress/models.py` |
| Shared transport | `src/agentgate/transport/mcp_security.py`, `src/agentgate/transport/mcp_envelope.py` |
| Deployment/client | `compose.yaml`, `scripts/start_lab.ps1`, `scripts/mcp_client.py`, `scripts/smoke_mcp.py`, `.github/workflows/ci.yml` |
| Tests | `tests/api/test_mcp_ingress.py`, `integration_tests/test_mcp.py` |
| Documentation | `README.md`, `docs/interactive_lab.md`, `docs/architecture.md`, `docs/threat_model.md`, `docs/final_quality_gates.md`, `docs/milestone_b_verification.md` |
| Existing OpenSpec change | `openspec/changes/add-interactive-lab/proposal.md`, `design.md`, `tasks.md`, `specs/mcp-ingress/spec.md` |

No generated credential, database, image or verification artifact is committed.
