# Design

## Context

See proposal.md for motivation and the three capability specs for behavioral contracts. The configured schema is `spec-driven`. The request-operation increment is implemented; this architectural refactoring preserves its simulation-only behavior and does not implement later use cases.

## Goals / Non-Goals

**Goals:** Use DDD, CQRS, Vertical Slice, and Hexagonal Architecture in one small FastAPI modular monolith; make domain invariants independent of adapters; make every dispatch pass through one execution path; preserve durable approval and at-most-once simulated effects; enforce architecture and security boundaries in CI.

**Non-Goals:** A general agent planner, arbitrary user tools, remote hosting, distributed execution, real banking, a web UI, production IAM, tamper-proof audit storage, and deployment automation. The host and database administrator are trusted; an agent request is untrusted. A compromised host or stolen approver credential is outside this demo's guarantee.

## Decisions

### 1. Modular monolith with inward dependencies

Use Python 3.12+, FastAPI, Pydantic v2 strict API models, stdlib `sqlite3`, and Uvicorn. Use Pytest, HTTPX, Ruff, and strict mypy for development. Domain and application use only the standard library and inward project imports. Pin the resolved direct/transitive dependency set in checked-in constraints; installation may use the network, runtime and tests do not.

Use one AgentGate bounded context in one process and one database. DDD describes the business model; CQRS separates write intent from inspection; Vertical Slice groups application behavior by use case; Hexagonal Architecture isolates adapters behind domain repositories and application-owned non-persistence ports. These are constraints on the same code, not four frameworks or services. A flat service module was rejected because it obscures use-case ownership and mixes orchestration with business rules. Microservices, mediator libraries, generic repository frameworks, and separate read/write databases add no value for this MVP.

Authoritative layout (existing slices shown; add future slices only when requested):

```text
src/agentgate/
  main.py                    # FastAPI bootstrap and router registration
  dependencies.py            # sole concrete composition root / DI
  components.py              # typed dependency bundle
  domain/
    entities/                # one entity per matching module
    value_objects/           # one value object/enum per matching module
    policies/                # pure rules; one policy class per file if needed
    repositories/            # Operation/Account/Approval/AuditRepository contracts
    events/
    exceptions/
  application/
    ports/                   # gateways and technical abstractions, never repositories
    exceptions/
  features/
    request_operation/
      endpoint.py            # owns POST /operations and its router
      command.py             # RequestOperationCommand
      handler.py             # RequestOperationHandler
      models.py              # this feature's strict Pydantic HTTP schemas
      result.py              # RequestOperationResult
    evaluate_policy/
      query.py               # internal EvaluatePolicyQuery, no HTTP endpoint
      handler.py             # EvaluatePolicyHandler
  infrastructure/
    repositories/            # concrete SQLite repositories, including audit
    persistence/             # connection/schema/unit of work/seeding
    gateways/                # LocalCredentialGateway; no new integration
    security/                # trusted configuration
    runtime/                 # clock and ID adapters
  transport/                 # shared middleware/error setup only; never endpoints
tests/
  domain/
  application/
  infrastructure/
  api/
  architecture/
```

These conventions supersede the earlier centralized HTTP and application/features layouts. Every endpoint lives in its corresponding `features/<use_case>/endpoint.py`; HTTP schemas for the same feature can share `models.py`. Use separate `command.py` or `query.py`, `handler.py`, and `result.py` when applicable. The existing policy evaluation remains an internal query with no endpoint; the example reconciliation gateway and get-operation feature are not implemented by this refactoring. Future approved use cases follow the same feature layout. Never create api/routes, controllers, or centralized endpoint folders.

Each Entity, Value Object/enum, domain Policy class, Repository/Gateway contract, and Handler has its own snake_case module. Domain and contract module names match their class names; feature classes use the role filenames above. No unrelated business classes in generic domain files or feature HTTP schema files, no classes in package initializers, and no compatibility re-export modules concealing ownership. Pure helper functions can stay in focused helper modules. Do not add a policy class or interface where a pure function or existing contract already suffices.

Persistence contracts belong exclusively in `domain/repositories/`, use the `Repository` suffix, and prefer Protocol or ABC. All concrete repositories, including audit persistence, live in `infrastructure/repositories/`. External integration contracts use `Gateway` under application ports when appropriate, with infrastructure gateway implementations. Actual event publishing uses `EventPublisher`; local AuditRepository persistence does not publish events or add a bus. Reject I-prefixed/generic interfaces and unnecessary abstractions. Technical Clock, PolicyEvaluator, OperationIdGenerator, RequestUnitOfWork, and RequestUnitOfWorkFactory contracts retain their precise roles.

| Area | Allowed dependencies | Enforced prohibitions |
| --- | --- | --- |
| `domain/` (including repository contracts) | Standard library and domain types | No application, features, bootstrap, transport, infrastructure, FastAPI, Pydantic, SQLAlchemy, SQLite, or I/O |
| `application/ports/`, `application/exceptions/` | Domain and application abstractions | No repositories here, concrete adapters, feature implementations, or framework types |
| Feature command/query/handler/result | Domain, application abstractions, own non-HTTP modules | No FastAPI/Pydantic/HTTP objects, infrastructure, root DI, or sibling-slice imports |
| Feature endpoint/models | Own contracts/handler/models, domain values, DI providers, HTTP frameworks | No SQL, concrete adapters, cross-feature implementations, or tool dispatch |
| `infrastructure/` | Standard library, domain, application abstractions | No feature, transport, bootstrap, or composition imports |
| `transport/` | HTTP frameworks and inward errors/types | No endpoints or concrete adapters |
| `dependencies.py` | Contracts, handlers, concrete adapters | Sole constructor wiring exception; no business policy, SQL, or dispatch |
| `main.py` | Bootstrap/DI/configuration and feature routers | Only initialize FastAPI, attach shared safeguards, and register routers; no endpoint/business implementations |

Dependencies point inward and remain acyclic, including relative, aliased, type-only, and re-exported imports. Domain repository contracts reference only domain types. Domain entities use value objects/policies/events/exceptions without a reverse dependency on entities. Only the future `features/execute_operation/harness.py` may invoke tools. Feature endpoints directly call constructor-injected handlers. No dynamic import, eval, exec, service locator, mutable global container, or framework injection in feature cores/domain/application abstractions/feature cores abstractions.

### 1.1 Pure domain model

- Entities: `Account` owns balance invariants; `Operation` owns immutable request identity and lifecycle transitions; `Approval` owns grant/reject/expiry/consumption rules. They are ordinary Python types with explicit methods, not Pydantic or persistence models. The unit of work provides atomicity across the operation, approval, and affected accounts rather than creating a large ledger aggregate.
- Immutable value objects: account/operation/principal IDs, positive USD money in integer cents, request fingerprint, decision/reason, policy version, and approval deadline. Domain validation rejects invalid values even when callers bypass HTTP. API validation provides transport errors but never replaces these invariants.
- Policies: pure authorization evaluation consumes an explicit trusted principal/permission snapshot, account facts, request, and policy version and produces ALLOW, DENY, or REQUIRE_APPROVAL. The application supplies current time and facts; the domain never fetches credentials, queries storage, or reads a clock.
- Events and exceptions: small immutable facts such as operation requested, approval decided, and operation executed plus typed invariant/transition exceptions. Handlers map facts to sanitized audit records within the same unit of work. Events are not the source of truth and are never published through a bus, outbox, or background worker.

### 1.2 Explicit CQRS handlers in use-case slices

Commands express intent and may persist state; queries inspect state and must not write business data or durable audit records. Commands may return IDs and result DTOs. Both share one SQLite schema with separate repository/read port methods; no projection pipeline, eventual consistency, or separate CQRS database is needed.

| Slice | Explicit request and handler | Responsibility |
| --- | --- | --- |
| `request_operation` | `RequestOperationCommand` / `RequestOperationHandler` | Authenticate context, validate domain values, evaluate policy, persist idempotent operation/approval request and decision audit; no tool dispatch |
| `evaluate_policy` | `EvaluatePolicyQuery` / `EvaluatePolicyHandler` | Pure decision over a supplied trusted snapshot; internal, with no new HTTP endpoint and no writes |
| `approve_operation` | `ApproveOperationCommand` / `ApproveOperationHandler` | Approver role check and atomic grant/reject plus audit; no tool dispatch |
| `execute_operation` | `ExecuteOperationCommand` / `ExecuteOperationHandler` | Owning-agent check and bounded runtime harness; only this slice may dispatch tools |
| `get_operation` | `GetOperationQuery` / `GetOperationHandler` | Authorized operation/result inspection via read port; no implicit execution or expiry persistence |
| `list_audit` | `ListAuditQuery` / `ListAuditHandler` | Approver-only bounded inspection through audit read port |

Request and execute handlers receive an application `PolicyEvaluator` port whose implementation is the evaluate-policy handler. The composition root injects it; slices never import or construct sibling handlers. Shared snapshots and decisions are domain values exposed through ports. Execution passes facts read inside its current unit of work to the evaluator; evaluation must not open a separate transaction or use stale cached facts. This preserves atomic reauthorization without a mediator or inter-slice dependency.

`get_balance` is a read-only tool, but invoking it through the operation lifecycle is an `ExecuteOperationCommand`: it persists dispatch/result/audit evidence. This differs from `GetOperationQuery` and `ListAuditQuery`, which only inspect already stored information. Repeated inspection never creates audit rows, consumes approvals, persists expiry, or alters balances; any derived expiry indicator in a read result does not change stored state.

### 1.3 Application ports, adapters, and constructor injection

Define only the ports needed by these slices: unit of work with operation/account/approval repositories and transactional audit writer; operation/audit readers; policy evaluator; fixed tool registry/execution; credential verifier; clock and retry sleeper. Use standard-library typed Protocols and explicit methods, not generic CRUD or a port for every helper. Query readers expose no write/commit method. The SQLite unit of work supplies repositories and audit writer on the same connection; repositories and tools never commit independently.

Adapters implement these contracts under infrastructure. Repositories map rows to domain entities/immutable domain snapshots and domain values back to SQL; query handlers map domain snapshots to their feature result types, so domain repository contracts never depend on feature results. The tool adapters load/change Account entities through the current transaction port and return typed results; they cannot override authorization. Credential verification maps configured tokens to a trusted domain principal, without passing the token onward.

`dependencies.py` explicitly constructs adapters and passes them to handler constructors at application startup, with request-scoped unit-of-work factories as needed. FastAPI Depends is allowed only at the API edge to retrieve constructed handlers/principals; handlers never call Depends or retrieve dependencies from global state. `main.py` calls the composition builder and registers routes. Tests construct handlers with fake ports and domain values, bypassing FastAPI, environment configuration, and SQLite. Commands and queries carry data, not adapters, and enforce their own role/ownership checks in handlers as well as API authentication.

Future LLM/MCP inbound adapters translate untrusted proposals to the same commands/queries and must obtain trusted principal context; they never receive an approval bypass, database handle, or policy override. A future remote side-effecting tool requires a new spec for cancellation and external idempotency; local atomicity cannot simply be reused.

### 2. Explicit local identities and fixed demonstration policy

Configure distinct high-entropy agent and approver bearer tokens through environment variables; validate at least 32 characters, reject documented sample values and duplicates, compare with constant-time comparison, and store neither token in SQLite. Map tokens to server-configured principal IDs, roles, tool sets, and source-account sets. Bind Uvicorn to `127.0.0.1` by default. Fail startup on invalid settings; do not generate permissive fallback credentials. Tests inject isolated credentials. A local human uses the approver credential through documented HTTP commands; there is no UI or external identity provider.

Seed `acct-alice` and `acct-bob` with 1,000,000 cents each in a fresh explicit demo database. Seeding is idempotent and never resets existing balances. The demo agent owns `acct-alice`, can read its balance, and can transfer to the other known account. Transfer policy v1 uses the boundaries in operation-authorization; amounts above 100,000 cents are denied even with approval. Reads require account ownership. Reject same-account transfers and non-USD requests. Current permissions and sufficient funds are checked again immediately before dispatch.

Static local credentials were chosen over OAuth because remote identity infrastructure would dominate the MVP. The credential holder is the identity boundary; the API cannot prove a human is physically present.

### 3. Small immutable HTTP contract

All endpoints are protected except an optional minimal health response with no configuration details. Body size is enforced while reading streamed chunks, not only through Content-Length. Feature-local HTTP Pydantic schemas forbid extra fields and coercion and translate into standard-library application request types and domain value objects; handlers never accept a Pydantic model or HTTP Request. Account IDs use `acct-[a-z0-9]{1,32}`. Amount input is bounded to signed 64-bit positive integer cents; syntactically valid values above the policy ceiling receive DENY. Tool arguments are a closed discriminated union. No free-form prompt, note, SQL, path, URL, or executable field exists.

| Endpoint | Contract |
| --- | --- |
| `POST /operations` | Agent submits `{tool, arguments}` with required `Idempotency-Key`; returns 201 for a new operation or 200 for replay; never dispatches a tool |
| `GET /operations/{id}` | Owning agent or approver reads sanitized operation state, decision, reason, approval metadata, result, and simulation marker |
| `POST /operations/{id}/approval` | Approver sends `{decision: APPROVE or REJECT}`; 200 on first valid decision, 409 on repeated/expired/nonpending request; never dispatches |
| `POST /operations/{id}/execute` | Owning agent supplies no operation arguments; dispatches only through harness and returns stored or new result |
| `GET /audit?after=...&limit=...` | Approver-only keyset pagination, default 50, range 1–100; increasing event ID order |

Each route maps to the corresponding Command/Query and directly calls its constructor-injected handler. Role/ownership enforcement also lives in the handler, so another inbound adapter cannot bypass authorization by avoiding HTTP. Policy evaluation remains an internal query, not an additional public API.

Operation submissions persist ALLOW, DENY, or REQUIRE_APPROVAL with a stable reason code. Schema errors return 422, oversized bodies 413, unauthenticated calls 401, role failures 403, and inaccessible operation IDs 404. Conflicting keys or pending/rejected/expired execution return 409; denied authorization returns 403. Timeout and terminal tool failure return a stored operation envelope with HTTP 200 and `TIMED_OUT` or `FAILED` status; infrastructure uncertainty returns 503. Every envelope identifies simulation mode. API errors and validation handlers discard raw inputs and exception messages.

The exact tool names are `get_balance` with arguments `{account_id}` and `simulate_transfer` with `{source_account_id, destination_account_id, amount_cents, currency}`. Currency is required and must be `USD`. Results are respectively `{account_id, balance_cents, currency}` and `{source_account_id, destination_account_id, amount_cents, currency}` inside the stored operation envelope. Canonicalization sorts field names and serializes only validated typed values, so JSON field order does not change a request fingerprint.

### 4. Separate policy decisions from operation and approval state

Persist the original decision and reason as immutable evidence. Operation states are `DENIED`, `PENDING_APPROVAL`, `READY`, `SUCCEEDED`, `REJECTED`, `EXPIRED`, `FAILED`, and `TIMED_OUT`. Initial ALLOW enters READY; REQUIRE_APPROVAL enters PENDING_APPROVAL. An approval row holds the request fingerprint, principal, policy version, creation/expiry times, decision, approver, and consumption time. Expiry is creation plus 300 seconds, including after grant; exactly the expiry instant is expired. UTC injected wall time handles expiry; monotonic time handles execution deadlines.

Approval changes PENDING_APPROVAL to READY or REJECTED under a conditional transactional update. It cannot edit arguments or execute. Execution of READY rechecks policy, version, allowlists, funds, and approval under the write transaction. An approved transfer retains its original REQUIRE_APPROVAL decision and adds effective ALLOW with `HUMAN_APPROVED` provenance. Policy-version mismatch is terminal DENIED and requires a new submission/key. Revalidation denial does not consume approval. Timeout and nonretryable execution failure are terminal; a user deliberately submits a new key to try again.

Use immutable operation arguments and a canonical JSON SHA-256 fingerprint of tool and typed arguments. A unique `(principal_id, idempotency_key)` constraint returns one operation for equivalent payloads, conflicts on different payloads, and does not deduplicate different principals. The execute endpoint accepts only an operation ID; approval IDs are not reusable bearer authorizations.

### 5. One local transaction is the side-effect boundary

Use one SQLite file, foreign keys, explicit schema version, and tables for accounts, operations, approvals, and audit events. Command repositories and query readers use this same database; SQL rows never escape infrastructure into domain or handlers. Operations store canonical arguments, fingerprint, principal, policy version, state, result, and timestamps. Balances have nonnegative integer constraints. Audit stores structured codes and IDs rather than raw bodies or headers. Only validated structured tool arguments are persisted in operations; never credentials or raw rejected payloads. Source/destination and amount are available through the owning operation, avoiding a second sensitive audit copy.

Submission and its decision audit are atomic. Approval and its audit are atomic. The execute handler's harness requests a write unit of work; the SQLite adapter implements it with `BEGIN IMMEDIATE`. Within that boundary: reread operation, authorize, invoke domain transitions through the registered local tool, update balances, consume approval, store result, and insert success audit before commit. A success-audit failure rolls back everything. Conditional state updates and write serialization prevent duplicate dispatch; a crash before commit rolls back and a crash after commit leaves the stored result for replay. No persistent RUNNING lease or recovery worker is necessary. Domain events are converted to audit rows before commit; event delivery is never required for correctness.

Before each transaction attempt, durably append a sanitized attempt event; if that write fails, do not dispatch. This event describes an attempted execution, not a committed effect. Rolled-back attempts remain visible. Failed or timed-out execution writes terminal state/audit in a separate bounded transaction after rollback. If storage is unavailable, return 503 and leave durable state authoritative; never claim execution or audit success. Authentication/validation rejection uses sanitized operational logs without inventing an operation record.

SQLite errors after an uncertain commit are not automatically retried. Reopen/read the operation: a terminal result is replayed; READY permits redispatch only after storage confirms no committed effect. If reconciliation is unavailable, keep returning 503. This is feasible because ledger changes and operation result share one transaction.

### 6. Cooperative deadlines with no background execution

The execute-operation slice owns the runtime harness, not the API or tool adapters. Two local tools perform bounded statements; there are no autonomous loops, nested tool calls, background tool workers, or fire-and-forget tasks. Each execute call gets one monotonic deadline at start, two transaction attempts maximum, and a single retry delay no longer than 50 ms. The application uses injected clock/sleeper and unit-of-work ports; SQLite busy waits and progress callbacks are infrastructure details capped by both 50 ms and remaining budget. Checks before dispatch, each mutation, and commit interrupt expired work. Infrastructure maps a proven rolled-back SQLite lock/busy error to a typed transient application error; only that class retries. Unknown errors, auth failures, and approval expiry never retry; retry revalidates authorization without resetting time.

A timeout means all uncommitted effects are rolled back, with no live worker able to commit later. A completed atomic commit is reported as success even if response delivery is delayed. The 2-second budget bounds dispatch/transaction eligibility; OS scheduling and an already-entered SQLite commit/fsync are not hard real-time interruptible. Returning a fictitious timeout after an actual commit would violate idempotency. Tests inject clocks, sleepers, and failure points rather than using long wall-clock waits. A future arbitrary blocking adapter is not supported by this contract.

### 7. Development harness and measurable verification

Use a single `pyproject.toml` for tool settings and documented commands: `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy --strict src`, and `openspec validate --all --strict`. Pin the OpenSpec CLI used by CI separately from Python dependencies. CI installs pinned dependencies, uses read-only repository permissions, runs on pull requests and default-branch pushes, and has a 10-minute job timeout. Test Python 3.12 and the explicitly documented newest supported interpreter; do not claim untested future compatibility.

Pytest covers pure entity/value-object/policy tests, individual command/query handlers using fake constructor-injected ports, adapter contract tests, in-process HTTP behavior, temporary file-backed SQLite concurrency/restart tests, transaction fault injection, and malicious payload/secret-sentinel checks. Query tests compare full business/audit state before and after repeated reads and use read-only fake ports that reject writes. Default test fixtures block outbound sockets and subprocess execution while allowing in-process HTTPX. A traceability document maps every scenario in all three specs to named tests or concrete documentation checks. AGENTS.md records dependency direction, slice ownership, CQRS semantics, constructor injection, offline simulation rules, commands, and proposal-review-apply discipline. Documentation includes an MIT license and a reproducible ALLOW/DENY/approval/replay walkthrough.

Architecture acceptance uses AST-based Pytest checks with one positive and negative fixture per rule: reject forbidden domain dependencies/I/O, outward imports, sibling-slice imports, dependency cycles, SQL or concrete adapters in handlers/routes, FastAPI/Pydantic in domain/application abstractions/feature cores, global service locators/framework DI in handlers, and tool dispatch outside the execute-operation harness. Resolve relative/aliased/type-only imports and re-exports rather than relying on string searches. Verify that only `dependencies.py` has the concrete wiring exception and that feature requests/handlers follow the explicit Command/Query contracts. Dynamic escape mechanisms remain banned; behavioral tests verify that queries do not write, domain invariants survive HTTP bypass, and handler authorization survives adapter replacement. Architecture tests are part of the ordinary Pytest/CI gate, with no additional architecture framework.

File-organization checks enforce one class per matching domain/contract module, one Handler per handler.py, and permit only feature-specific HTTP schemas grouped in models.py. No classes appear in package initializers. Checks reject centralized endpoint directories, endpoints outside features, repositories outside domain/repositories, and HTTP imports in feature cores. Positive/negative fixtures cover dedicated entity/value/command/query/handler files, Protocol/ABC contracts, Repository/Gateway/EventPublisher naming by responsibility, and rejection of generic I-prefixed/Base names. These checks run with the existing dependency/cycle/DI checks and preserve the established behavior regression suite.

## Risks / Trade-offs

- Local static credentials and approver trust → restrict the default bind address, document token handling and local-only assumptions, enforce separate roles and source ownership.
- SQLite serializes writes → keep tools and transactions short; demonstrate concurrency correctness, without promising production throughput or multi-worker operation.
- Cooperative deadlines do not provide hard real-time scheduling → allow only the two bounded local tools, check before commit, and report committed results truthfully.
- Audit cannot be written during total storage failure → fail closed with 503 and sanitized operational logs; never promise a durable event where persistence is impossible.
- Database administrators can edit audit or clock → document trusted-host limits; external append-only logging and stronger identity are future work.
- Sample policy values are educational defaults → version them explicitly; require a new reviewed specification for materially different policy or external side effects.
- Architecture introduces more directories for a tiny service → keep one bounded context, concrete use cases, small Protocols, direct handler calls, one database, and no generic mediator/event infrastructure.

## Migration Plan

There is no existing application data to migrate. Implementation creates a versioned initial schema and explicitly seeded local database. Unknown schema versions fail startup. Verification uses disposable databases; a manual upgrade backs up the local database before replacement. Rollback restores that backup with a matching application version. No production deployment or destructive automatic reset is included.
