# Design

## Context

See proposal.md for motivation. The baseline has 925 tests, six domain repository contracts, synchronous handlers, a two-second execution deadline, SQLite schema v6 and atomic unit-of-work boundaries. Inspection uses read-only repositories. Only the execute slice's harness dispatches the two local simulation adapters. There are no main specs yet; baseline requirements live in the active agentgate-core change.

## Goals / Non-Goals

Goals: adapter parity, persistent local demonstration, independent security/concurrency evidence, and one coherent A deliverable. Preserve all domain and handler safeguards and constructor injection.

Non-goals for A: MCP/LLM runtime, real financial or remote tool effects, production deployment, automatic migration of SQLite data, new branches, commits, publication or archival.

## Decisions

1. **One selected database.** Use the existing database configuration to select PostgreSQL by URL, otherwise SQLite. Wire all adapters in dependencies.py. PostgreSQL repositories implement the existing contracts; do not put SQL in slices. Share pure row hydration where useful while keeping backend-specific parameter binding and transaction semantics explicit. Avoid an ORM/mediator because the existing domain and contracts already define the boundaries.
2. **Explicit PostgreSQL serialization.** Use READ COMMITTED command transactions plus a fixed transaction-scoped advisory lock acquired before any authoritative reads. This intentionally serializes the small local simulation (including submissions and approval), matching SQLite's coarse writer semantics, preventing lost updates and duplicate key races across API processes. Do not use session or process locks. Keep statement/lock waits bounded by the existing deadline; classify only confirmed rolled-back lock/deadlock/serialization errors as transient. Reads use REPEATABLE READ READ ONLY snapshots without the writer lock. This sacrifices throughput for simple, auditable parity.
3. **Schema and recovery.** Version the PostgreSQL schema independently; transactional initialization under a separate advisory lock creates schema v1 with all current fields, constraints, unique principal/key and operation/attempt pairs. Seed with ON CONFLICT DO NOTHING only in explicit lab startup. Repositories never commit. UoW alone commits/rolls back, conservatively reports uncertain commits, and permits existing handler reconciliation. Unknown versions fail closed. PostgreSQL BIGINT keeps balances within domain integer bounds.
4. **Local deployment.** Compose runs PostgreSQL 16, the API and a separate lab proxy serving static HTML/CSS/JS. Only frontend 127.0.0.1:8080 and API 127.0.0.1:8000 publish ports; database has no published port. Named volume persists data. PowerShell generates distinct random secrets into ignored local secret files, reused on restart and mounted read-only. No credentials in YAML, image layers or browser assets. Startup does not remove volumes or reset accounts.
5. **Constrained demo proxy.** A feature-local endpoint adapter forwards only fixed method/path workflows to the internal API using an injected gateway. Agent and approver tokens stay server-side. The browser chooses explicit human approve/reject controls; model integration does not exist. Validate exact allowed Host and same-origin requests, forbid cross-site fetch metadata, require a session-bound CSRF header on mutations, reject arbitrary body fields through upstream strict schemas, and never forward browser authorization or custom destinations. Render data with textContent. Set no-store and restrictive CSP. This local demo is not a production identity or multi-user authorization system.
6. **Read balances.** Add an approver-only account-inspection query using a read-only adapter implementing the existing AccountRepository facts method, with save rejected. The lab uses approver credentials for balance snapshots; unlike executing get_balance it creates no operation/audit noise. Existing agent source permissions stay unchanged.
7. **Swagger.** Explicit local-development configuration enables /docs and /openapi.json; default remains disabled. Local Host validation protects enabled documentation; Compose's loopback binding provides the network boundary. No credential injection into Swagger.
8. **B and C contracts.** B adds a separate authenticated MCP ingress adapter translating to existing use cases; agent tools never grant approval. C adds a server-side model gateway and chat slice translating untrusted suggestions through B. Provider configuration remains server-side; human approval remains outside the model tool set. Use fake transports/models for tests. No outbound integration is implemented during A.

## Milestone B transport decisions

Milestone B implementation authorization extends decision 8: use the official
`mcp==2.3.0` SDK low-level Server callbacks, with strict Pydantic HTTP-boundary
schemas and fixed sanitized validation errors. A separate `mcp.py` ASGI factory
enters the SDK Streamable HTTP lifespan once, uses stateless JSON responses and
closes its shared HTTP client. `dependencies.py` alone constructs the agent-only
HTTP gateway. Calls go through the existing FastAPI API, never directly to CQRS
handlers, repositories or tools. HTTP execution sends a truly empty body.

Compose publishes MCP only at 127.0.0.1:8002; its service mounts independent MCP
and agent secrets, with no approver/database credential or persistence network.
Authentication and exact Host/Origin checks precede body buffering and the SDK;
SDK DNS rebinding protection remains enabled. Request bodies are capped at 16
KiB, HTTP waits are explicit, redirects/proxy inheritance are disabled, and no
rejected raw arguments or exception details enter tool errors. All clients map
to the existing local AGENT, with no multi-user OAuth claim. Approval stays in
the independent existing human workflow. Real official-SDK Docker smoke covers
initialization, discovery, modern negotiation, policy, human approval,
concurrency, immutable PostgreSQL bindings and replay after API/MCP restart.
Offline tests still forbid network/subprocess access. B created no new branch,
commit, push or archive; C is separately authorized below.

## Risks / Trade-offs

- Coarse writer serialization limits throughput → intentional for a two-account local lab; concurrency tests verify behavior and bounded contention.
- Lost commit acknowledgment → retain conservative CommitUncertain classification and durable reconciliation; never infer rollback from a disconnected client.
- Local browser drive-by requests → exact Host/Origin, fetch metadata, session CSRF and loopback publishing; no generic proxy.
- PostgreSQL secrets outlive containers → ignored secret files and named volume must be retained together; document manual recovery rather than silently rotating a live database password.
- Tests need real PostgreSQL for isolation evidence → opt-in disposable test database/service, separate from the persistent demo; default 925 tests remain offline.
- Synthetic human controls are educational → production identity/session management remains outside A.

## Migration Plan

Validate the complete A/B/C artifacts first, then apply A on the current branch. Preserve SQLite as default and run its full regression suite. Initialize PostgreSQL only on explicit selected configuration; no automatic data copy. Build Compose, run integration and smoke tests, exercise all decisions and replay across container restart, then document verified results. Roll back deployment by stopping containers without deleting the data volume or secrets. B is authorized on the current branch without creating branches, commits, pushes or archive. Continue C only after separate authorization under this change.

## Milestone C agent decisions

C is now explicitly authorized on the existing `feat/llm_and_chat` branch, as
clarified by the user. Preserve all A/B domain policy and financial semantics;
no new branch, commit, push or archival is authorized.

The existing frontend proxy hosts a framework-free `chat_turn` command handler
with injected model, official-SDK MCP client, bounded process-local chat sessions
and operation-ID generator ports. Infrastructure adapters handle HTTPS provider
requests and authenticated Streamable HTTP; the orchestrator never bypasses MCP
with direct FastAPI or repository calls. No new framework, public port, business
tool or persistence contract is needed.

Configure OpenAI or Groq and a model through environment/file secrets, with exact
provider origins, finite timeout/token/call/history limits and a forced harmless
function capability probe. Missing keys/configuration disable chat while manual
controls remain operational. Offline CI uses deterministic fake providers and
in-memory real MCP protocol exchanges. A separately explicit test overlay permits
browser/Docker QA with a fake LLM and actual MCP/API/PostgreSQL; it is never a
production fallback. Real-provider verification is opt-in and reported unverified
when valid credentials are unavailable.

The model sees discovered allowed MCP schemas, without the backend-owned
idempotency key. Strict validation and domain values reject unknown tools,
roles, extra fields and malformed arguments. Transfer execution requires an
explicit UI command granting one invocation for that exact known operation ID;
user text grants neither execution nor business approval. Approval stays in the
independent human adapter. Balance reads can execute automatically. Actual API
handlers retain authority over policy, funds, ownership, immutable bindings and
replay. Sanitized MCP operation cards and events are distinct from model prose,
which is explicitly unverified.

A pending mutation records its original payload/key before I/O and blocks new
proposals until explicit identical recovery. Timeouts, disconnection and
cancellation cannot cause automatic retry with a fresh key. Chat is bounded to
64 sessions, 32 cards, one active turn/session and one-hour idle TTL; frontend
restart clears chat memory, while PostgreSQL business state remains durable.
After losing session memory, users must inspect existing operations before
creating another proposal. This local single synthetic identity lab is not
production multi-user authorization or a guarantee of model correctness.
