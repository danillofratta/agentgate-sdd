# Spec Delta

## Purpose

Make AgentGate's development constraints repeatable and reviewable through executable quality gates and explicit links between specifications and tests.

## ADDED Requirements

### Requirement: Reproducible local development
The project SHALL document installation and verification on Python 3.12+, provide pinned direct and transitive dependencies, and run application tests without network access, paid services, real credentials, LLMs, or MCP servers.

#### Scenario: Clean environment verification
- **WHEN** a contributor installs the pinned dependencies on Python 3.12 and follows the documented verification commands
- **THEN** tests, lint, formatting checks, and strict type checks pass without external services or runtime network access

### Requirement: Enforced quality gates
Every pull request SHALL run tests, lint, formatting checks, strict type checking, architectural checks, and strict OpenSpec validation in CI. A failure in any gate SHALL fail the workflow.

#### Scenario: Quality gate failure
- **WHEN** a pull request contains a failing test, lint violation, formatting error, type error, invalid active spec, or forbidden architectural dependency
- **THEN** CI reports failure for the corresponding required check

### Requirement: Architectural isolation
The harness SHALL enforce inward dependencies: domain uses only standard-library/domain types; feature cores use domain repositories and application abstractions; adapters use inward contracts. Only root dependencies.py SHALL wire concrete adapters to handlers. Feature endpoints SHALL NOT access persistence/tools directly. Only the execute-operation harness SHALL dispatch tools.

#### Scenario: Forbidden dependency is detected
- **WHEN** an architectural check inspects a fixture containing a forbidden import or direct tool dispatch outside the execution harness
- **THEN** the check fails and identifies the offending dependency or dispatch

#### Scenario: Domain purity and inward imports
- **WHEN** architecture fixtures introduce a framework, validation-library, database, environment, or I/O dependency in domain, or an infrastructure/API import in application
- **THEN** the architecture gate fails with the offending file and dependency, including relative, aliased, type-only, and re-exported imports

#### Scenario: Composition exception is narrow
- **WHEN** a route or handler constructs a concrete repository/tool adapter, or an adapter imports an HTTP route or feature handler
- **THEN** the architecture gate rejects it while allowing concrete constructor wiring only in root dependencies.py

### Requirement: Feature-local HTTP adapters
Every endpoint SHALL reside in features/<feature_name>/endpoint.py. HTTP schemas for that feature MAY share models.py. Command/query/handler/result files SHALL remain separate and handlers SHALL NOT depend on HTTP frameworks or schemas. main.py SHALL only bootstrap FastAPI and register feature routers. Centralized endpoint directories SHALL be forbidden.

#### Scenario: Endpoint placement and handler purity
- **WHEN** fixtures declare centralized api/routes or controllers, an endpoint outside its feature, or a FastAPI/schema dependency in a handler
- **THEN** architecture checks fail while allowing feature-local endpoint.py/models.py and preserving the existing API contract

### Requirement: Domain-owned repository contracts
Every Repository contract SHALL live in domain/repositories with the Repository suffix and one contract per file. Concrete repositories SHALL live in infrastructure/repositories. Domain SHALL remain free of application, feature, HTTP framework, database-library, and infrastructure dependencies. Entities, Value Objects, and Policy classes SHALL each have their own file.

#### Scenario: Repository ownership and domain organization
- **WHEN** a fixture places a Repository in application/ports, groups domain classes, or imports a framework/adapter into domain
- **THEN** architecture checks fail; domain repository Protocols and infrastructure implementations pass

### Requirement: Pure business model
Domain entities, value objects, policies, events, and exceptions SHALL express business invariants independently of HTTP, validation frameworks, persistence, configuration, or real clocks. Entity transitions and value construction SHALL enforce invariants without relying on API validation.

#### Scenario: Domain tested without adapters
- **WHEN** domain tests construct values and invoke operation, approval, and account transitions directly using explicit facts and times
- **THEN** valid transitions succeed, invalid values/transitions fail, and no framework, storage adapter, environment, network, or system clock is needed

### Requirement: Use-case slices and explicit CQRS
Features SHALL organize explicit Commands, Queries, and Handlers by use case under features/<feature_name>. Slice cores SHALL depend on domain repositories and application abstractions rather than sibling-slice implementations. Queries SHALL NOT mutate business or durable audit state. Commands and queries SHALL share one database without a mediator, event bus, or separate CQRS database.

#### Scenario: Slice boundaries and request contracts
- **WHEN** architecture checks inspect feature handlers and fixtures that import sibling features, form dependency cycles, or mix command/query responsibilities
- **THEN** explicit request/handler contracts pass and the violating fixtures fail without requiring a dispatch framework

### Requirement: Constructor-injected application ports
Handlers SHALL receive required collaborators through constructors typed by domain repository contracts or application ports. They SHALL NOT construct infrastructure adapters, resolve dependencies from global state, or use framework injection. Root dependencies.py SHALL supply concrete adapters; tests SHALL substitute fakes without changing business logic.

#### Scenario: Handler isolation and dependency injection
- **WHEN** a command or query handler is constructed with fake ports and trusted principal data outside the web application
- **THEN** its use case runs with the same authorization and invariants, without concrete persistence or HTTP dependencies

#### Scenario: Hidden dependency resolution is rejected
- **WHEN** a fixture uses a service locator, mutable global container, framework injection, or concrete adapter creation inside a handler
- **THEN** the architecture gate fails and identifies the hidden dependency

### Requirement: Contributor and specification guidance
The project SHALL provide AGENTS.md with development commands, inward dependencies, domain purity, slice/CQRS boundaries, constructor injection, security rules, and the propose/review/apply/verify workflow. Each capability scenario SHALL map to at least one named automated test or an explicit documentation check in a traceability table.

#### Scenario: Acceptance coverage review
- **WHEN** a reviewer follows the traceability table for every scenario in this change
- **THEN** each entry identifies an existing passing test or a reproducible documentation check, including malicious-input and failure-path scenarios

### Requirement: Public demonstration documentation
The project SHALL include an MIT license and document local setup, simulation-only limits, threat model, API examples for all three decisions and approval replay, and future adapter contracts without enabling external integrations.

#### Scenario: Demonstration walkthrough
- **WHEN** a contributor executes the documented examples against a fresh local database
- **THEN** they observe ALLOW, DENY, REQUIRE_APPROVAL, human approval, exactly one simulated transfer, and matching sanitized audit evidence
