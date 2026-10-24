# Proposal

## Why

AgentGate will demonstrate how specification-driven development and a runtime agent harness reinforce each other. A small, entirely simulated financial service makes authorization, human oversight, bounded execution, and adversarial testing observable without transaction costs or external AI dependencies.

## What Changes

- Introduce a Python 3.12+ FastAPI service using Pydantic and SQLite, with deterministic policies and two registered tools: balance lookup and simulated transfer.
- Structure the service as a modular monolith combining DDD, CQRS, Vertical Slice, and Hexagonal Architecture: pure domain entities/value objects/policies, explicit use-case Commands/Queries/Handlers, domain-owned repository contracts, application integration/technical ports, and infrastructure adapters.
- Enforce inward dependencies and constructor-based dependency injection, with FastAPI and Pydantic confined to the API boundary. Keep one SQLite database and direct handler calls; introduce no mediator, event bus, or separate CQRS database.
- Return ALLOW, DENY, or REQUIRE_APPROVAL, with trusted caller identities, tool allowlists, durable human approval, idempotency, and transactional audit records.
- Enforce input limits, least privilege, secret redaction, execution deadlines, bounded retries, and fail-closed behavior.
- Establish a development harness with OpenSpec, AGENTS.md, Pytest, Ruff, mypy, CI, and architecture tests for domain purity, inward imports, slice isolation, command/query separation, dependency injection, and sole harness dispatch.
- Document narrow interfaces for future agent, LLM, and MCP adapters without implementing or depending on them.
- Keep the MVP local and single-process; exclude real transactions, external network tools, distributed workers, UI, model calls, and production identity infrastructure.

## Capabilities

### New Capabilities

- `development-harness`: Reproducible quality gates, specification traceability, enforced DDD/CQRS/Vertical Slice/Hexagonal boundaries, and contributor instructions.
- `operation-authorization`: Adapter-independent domain invariants, validated simulated operations, caller permissions, deterministic policy, and human approval lifecycle.
- `execution-control`: Idempotent, bounded command execution, side-effect-free inspection queries, atomic simulation, controlled retries, and durable audit evidence.

### Modified Capabilities

None. The repository currently contains OpenSpec scaffolding and generated workflow instructions, with no application, tests, or existing capability specs.

## Impact

Implementation will add a small `src/agentgate/` package, `tests/`, `pyproject.toml`, reproducible dependency constraints, CI, AGENTS.md, and public project documentation including an MIT license. Runtime dependencies are FastAPI, Pydantic, and Uvicorn; storage and execution primitives use the standard library. Development dependencies are Pytest, HTTPX for in-process API tests, Ruff, and mypy. No paid service, real financial credential, ORM, agent framework, LLM SDK, or MCP SDK is required.

The package is organized as `domain/`, `features/<use_case>/`, `application/ports/`, `infrastructure/`, root bootstrap/DI, and feature-local HTTP adapters. Entities own business transitions; handlers orchestrate ports; adapters implement persistence, audit, authentication, and the two local tools. Features cover requesting, evaluating policy, approving, executing, and reading operations, plus the already-scoped audit listing. Small domain event values represent business facts without event sourcing or asynchronous delivery.

Acceptance is defined by the capability scenarios: architecture violations fail CI; domain/handler tests run without FastAPI or concrete storage; queries never mutate business or audit state; and exact policy boundaries, approval expiry and replay prevention, concurrent idempotency, atomic audit/ledger writes, deterministic timeout/retry tests, and malicious-input rejection remain enforced. This change produces planning artifacts only; implementation requires a separate apply request.
