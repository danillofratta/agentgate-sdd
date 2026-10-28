# AgentGate contributor instructions

Read the selected OpenSpec artifacts before editing. Planning requests authorize
artifacts only; implementation requests authorize their stated increment. Mark
tasks complete only after their full behavior and verification are satisfied.
Propose, review, apply, verify; archive only when separately requested.

## Authoritative architecture

Use DDD, CQRS, Vertical Slice, and Hexagonal Architecture in one modular monolith.
These conventions replace older conflicting layouts.

- Every feature lives at `backend/services/agentgate/src/agentgate/features/<feature_name>/`.
- A feature owns its `endpoint.py`, `command.py` or `query.py`, `handler.py`,
  `models.py` (HTTP schemas), and `result.py`, when applicable.
- Every endpoint/router belongs to its feature's `endpoint.py`. Never create
  `api/routes/`, `controllers/`, or another centralized endpoint folder.
- `main.py` only bootstraps FastAPI, configures shared transport, and registers
  feature routers. `dependencies.py` is the sole concrete composition/DI root.
- Every repository contract lives in `domain/repositories/`, named
  `*Repository`, using Protocol or ABC. Never put repositories in application ports.
- Concrete repositories live in `infrastructure/repositories/`. Gateway contracts
  can live in `application/ports/`, with implementations in infrastructure/gateways.
- Persistence uses `Repository`, external integrations use `Gateway`, and actual
  event publishing uses `EventPublisher`. Do not introduce I-prefixed or generic
  contracts or add publishers/gateways without a real use case. Local audit
  persistence uses `AuditRepository`; it does not publish events.

- The Python project root is `backend/services/agentgate/`; source-local paths below are relative to that project.
- Domain enums belong in `domain/enums/`; genuine Value Objects remain in `domain/value_objects/`.
- Browser assets/tests and the Nginx build belong to `frontend/apps/lab-console/`; it contains no backend credentials or Python runtime.
- Cross-application acceptance lives in `tests/e2e/`. Root Compose preserves existing volume names and secret paths.

## Dependency rules

| Area | Allowed project dependencies |
| --- | --- |
| domain | domain only; standard library; no I/O, environment, real clock reads, or third-party libraries |
| application/ports and exceptions | domain and application abstractions; no feature implementations |
| features/<use_case>/command, query, handler, result | domain, application abstractions, own non-HTTP slice modules |
| features/<use_case>/endpoint.py | own models/requests/handler, domain values, DI providers; no persistence or tools |
| features/<use_case>/models.py | Pydantic and own HTTP schema definitions |
| infrastructure | domain and application abstractions; no features, transport, bootstrap, or DI imports |
| transport | shared HTTP middleware/errors; no business endpoints or concrete adapters |
| dependencies.py | concrete adapter/handler constructor wiring exception |
| main.py | FastAPI bootstrap, components, DI, shared HTTP configuration, and feature routers |

Keep imports inward and acyclic, including relative/aliased/type-only imports.
Feature implementations never import sibling slices. Constructor-inject ports
into handlers; no framework DI, FastAPI, Pydantic, or HTTP Request objects in
handlers, commands, queries, or results. FastAPI Depends is confined to endpoint
adapters and root DI providers. Commands and queries remain separate. Queries
cannot mutate business or durable audit state. Use one SQLite database; no
mediator, event bus, event sourcing, or separate CQRS databases. Only the future
execute-operation harness may dispatch tools; submission never dispatches.

## File organization

Use snake_case. Every Entity, Value Object/enum, domain Policy class, Repository,
Gateway, and Handler has its own file. Domain class modules match the full class
name in snake_case; generic domain files grouping unrelated classes are forbidden.
Within features, use the role filenames above (`handler.py`, `command.py`, etc.).
HTTP schemas belonging to that feature may share `models.py`; business classes
must not be hidden there. Package initializers define no classes. Technical
contracts keep precise names such as Clock, PolicyEvaluator, OperationIdGenerator,
RequestUnitOfWork, and RequestUnitOfWorkFactory. Do not create unused interfaces.

## Security and verification

Simulation only: no real transactions, outbound tools, LLM/MCP integrations,
subprocess tools, or arbitrary execution. Never add permissive fallback policy or
sample/default credentials. Never expose secrets, authorization headers, rejected
raw input, or exception details. Keep request/approval/audit persistence atomic.

From `backend/services/agentgate/`, use `uv sync --locked --python 3.12`, then `uv run --locked pytest`,
`uv run --locked ruff check .`, `uv run --locked ruff format --check .`,
`uv run --locked mypy --strict src`, and run `openspec validate --all --strict` from the repository root.
Architecture tests are part of Pytest. Tests use fake ports/time and temporary
SQLite databases; outbound network and subprocesses are blocked. Verify policy
boundaries, direct-handler authorization, idempotency/concurrent/restart replay,
malicious inputs, and rollback on audit failure. Never call real services in tests.
