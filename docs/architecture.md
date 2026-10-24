# Architecture

AgentGate is one bounded context in one modular monolith. DDD isolates business
invariants, CQRS makes write intent explicit, Vertical Slice keeps each use case
together, and Hexagonal Architecture protects the core from concrete I/O.
These conventions use Python types and Protocols without additional frameworks.

## Layout

```text
src/agentgate/
  main.py                       FastAPI factory and router registration
  dependencies.py               sole concrete composition/DI root
  components.py                 typed bundle of constructed collaborators
  domain/
    entities/                   Account, Operation, Approval
    value_objects/              immutable IDs, money, enums, snapshots
    policies/                   pure operation_policy evaluation
    repositories/               persistence/read contracts using domain types
    events/                     immutable facts, no event delivery
    exceptions/                 typed invariant failures
  application/
    ports/                      UoW, policy, identity, tools, clock, sleeper, IDs
    exceptions/                 orchestration/storage failures
    execution_deadline.py        injected monotonic deadline
  features/
    request_operation/          endpoint, models, command, handler, result
    approve_operation/          endpoint, models, command, handler, result
    execute_operation/          endpoint, models, command, handler, result, harness
    get_operation/              endpoint, models, query, handler, result
    list_audit/                 endpoint, models, query, handler, result
    evaluate_policy/            internal query and handler
    expire_approval/            internal command and handler
  infrastructure/
    repositories/               SQLite implementations and row mapping
    persistence/                schema v6, connection, UoW, explicit seed
    gateways/                   local credentials/principals and fixed registry
    tools/                      two local simulation adapters
    runtime/                    real clock, sleeper, UUID generator
    security/                   trusted environment settings
  transport/                    shared body limit and sanitized HTTP errors
tests/
  domain/ application/ infrastructure/ api/ architecture/
```

Each Entity, Value Object/enum, policy class and contract has its own snake_case
module matching its full class name. Feature classes use role filenames; HTTP
schemas for one feature may share `models.py`. Package initializers define no
classes. Endpoints belong exclusively in their slice's `endpoint.py`; there is
no centralized `api/routes/` or `controllers/` directory.

## Allowed import matrix

Rules include relative, aliased, type-only and re-export imports. The dependency
graph must remain acyclic.

| Area | Allowed project dependencies and external dependencies | Boundary |
| --- | --- | --- |
| `domain/` | Domain and standard library | No I/O, environment, real clock reads, frameworks, SQLite or third-party library |
| `application/ports`, exceptions, deadline | Domain and application abstractions | No feature implementations or concrete adapters |
| Feature command/query/handler/result/harness | Domain, application abstractions, own non-HTTP slice | No sibling slices, HTTP, Pydantic, concrete adapters or root DI |
| Feature `endpoint.py` | Own schemas/request/handler, domain values, DI providers; FastAPI | No SQL, concrete storage or tool dispatch |
| Feature `models.py` | Own HTTP schemas; Pydantic | No business classes |
| `infrastructure/` | Domain and application abstractions; standard library I/O | No features, transport, bootstrap or DI imports |
| `transport/` | Shared inward errors/types; HTTP libraries | No business routes or concrete adapters |
| `dependencies.py` | Contracts, handlers and concrete adapters; FastAPI providers | Sole concrete constructor wiring exception; no business rules, SQL or dispatch |
| `main.py` | Components, DI, shared HTTP configuration and feature routers; FastAPI | Bootstrap only |

```mermaid
flowchart TD
    Main[main.py] --> DI[dependencies.py]
    Main --> Edge[Feature endpoint.py]
    Edge --> DI
    Edge --> Slice[Own request and handler]
    DI --> Slice
    DI --> Adapters[Infrastructure adapters]
    Slice --> Ports[Application ports]
    Slice --> Domain[Pure domain and repository contracts]
    Ports --> Domain
    Adapters --> Ports
    Adapters --> Domain
```

[`tests/architecture`](../tests/architecture) checks import direction, cycles,
class/file organization, CQRS, hidden dependency resolution and dispatch placement.
AST checks are regression gates, not a sandbox against hostile Python packages.

## Command/Query/Handler map

Each request lives in its slice's `command.py` or `query.py`, and each handler
in its own `handler.py`.

| Slice | Request | Handler | HTTP / responsibility |
| --- | --- | --- | --- |
| request_operation | RequestOperationCommand | RequestOperationHandler | POST /operations; idempotent creation, policy, pending approval and audit |
| approve_operation | ApproveOperationCommand | ApproveOperationHandler | POST /operations/{id}/approval; one independent grant/reject and audit |
| execute_operation | ExecuteOperationCommand | ExecuteOperationHandler | POST /operations/{id}/execute; owner authorization, harness, attempts, recovery and replay |
| get_operation | GetOperationQuery | GetOperationHandler | GET /operations/{id}; owner/approver inspection |
| list_audit | ListAuditQuery | ListAuditHandler | GET /audit; approver-only bounded inspection |
| evaluate_policy | EvaluatePolicyQuery | EvaluatePolicyHandler | Internal pure query on supplied trusted facts; no endpoint or writes |
| expire_approval | ExpireApprovalCommand | ExpireApprovalHandler | Internal explicit atomic expiry and audit; no endpoint, worker or scheduler |

Queries never change balances, operations, approvals, results, expiry or durable
audit. Read repositories use read-only connections to the same SQLite database.
`get_balance` dispatch is an execution command, distinct from inspection.
There is no mediator, event bus, event sourcing or asynchronous projection.
Domain event values describe facts; `AuditRepository` persists evidence in a
transaction. Creating an event does not publish it or prove its commit.

## Contracts and constructor wiring

All six persistence contracts live in
[`domain/repositories/`](../src/agentgate/domain/repositories): `AccountRepository`,
`OperationRepository`, `ApprovalRepository`, `AuditRepository`,
`OperationReadRepository` and `AuditReadRepository`. Methods use domain types,
never HTTP schemas, feature results or SQL rows. Implementations live in
[`infrastructure/repositories/`](../src/agentgate/infrastructure/repositories).

Actual application port names are `RequestUnitOfWork`, `RequestUnitOfWorkFactory`,
`PolicyEvaluatorGateway`, `CredentialGateway`, `PrincipalGateway`,
`ToolRegistryGateway`, `ClockGateway`, `SleeperGateway` and
`OperationIdGeneratorGateway`. No generic CRUD contract or unused publisher is
required. Local audit is persistence, not event publication.

This executable excerpt follows
[`build_components`](../src/agentgate/dependencies.py). It illustrates root wiring;
handlers must not import these concrete adapters:

```python
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.runtime.system_clock import SystemClock
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator

database = "agentgate.sqlite3"
request_handler = RequestOperationHandler(
    lambda: SqliteUnitOfWork(database),
    EvaluatePolicyHandler(),
    SystemClock(),
    UuidOperationIdGenerator(),
)
```

Request and execute handlers accept the policy port; only root DI knows its
implementation is the evaluation handler. Slices never import one another.
Tests substitute fake ports and explicit principal/time values without FastAPI
or SQLite. FastAPI `Depends` stays in endpoints and root providers. Handlers
enforce authorization when HTTP is bypassed; an alternate adapter must obtain
trusted principal context rather than trust caller-asserted roles.

## Execution Harness and Unit of Work

The handler owns transaction attempts, persisted attempt evidence, identity
refresh, terminal replay and recovery. Its slice-local `Harness` alone invokes
`ToolRegistryGateway.dispatch`, revalidates policy/funds/approval, checks the
deadline, validates results and applies account transitions. Tool adapters receive
immutable arguments/account snapshots without a database or commit handle.
The harness applies `Account.transfer_to` and saves through the current UoW.

The UoW shares one connection among account, operation, approval and audit
repositories. SQLite `BEGIN IMMEDIATE`, uniqueness/conditional updates and
nonnegative integer balance constraints protect local concurrency. Balances,
result, approval consumption, dispatch and success audit commit together.
Attempt evidence commits before dispatch in a separate transaction; rolled-back
attempts remain visible. Terminal failure recording follows confirmed rollback
in a separate bounded recovery transaction. Storage failure can prevent terminal
evidence; the application does not invent durable success or audit records.

Two seconds of monotonic time cover at most two attempts and one retry delay of
at most 50 ms. Only proven rolled-back transient locks retry, without resetting
the deadline. Unknown/authorization/validation failures do not retry. Uncertain
commits require durable reconciliation before later dispatch. Scheduling and an
entered commit/fsync are not hard real-time interruptible; committed results
are reported truthfully. See [execution](execution_harness.md) and
[persistence/recovery](persistence.md).

## Future integrations

There is no external MCP or LLM integration. Future inbound adapters would
translate untrusted proposals to the same commands/queries after trusted
authentication. They must not provide policy overrides, replacement approved
arguments or direct tool/database access. A future outbound integration would
implement an application `Gateway` under infrastructure; persistence remains a
domain `Repository`. Add an `EventPublisher` only for a real publishing use case.

Remote side effects require a separately reviewed specification for external
idempotency, cancellation, reconciliation and distributed failures. Local SQLite
atomicity is not a production-grade distributed transaction. No remote service,
SDK, framework or paid dependency is introduced here.
