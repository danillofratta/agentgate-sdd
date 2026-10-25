# Spec Delta

## Purpose

Define the Milestone B MCP entry point for untrusted agent requests while retaining AgentGate's application authorization and explicit execution boundary.

## ADDED Requirements

### Requirement: Authenticated application ingress
MCP SHALL use a pinned stable official Python SDK and Streamable HTTP. Exactly request_operation, get_operation and execute_operation SHALL call the existing FastAPI submission, inspection and execution endpoints. Principal ownership, bounded strict inputs, idempotency and sanitized failures SHALL preserve HTTP semantics. Transport handlers SHALL contain no business rules, repository access, SQL or simulation dispatch.

#### Scenario: Fixed tool arguments
- **WHEN** a client discovers and invokes tools
- **THEN** execution and inspection accept only operation_id, while submission accepts only tool_name, structured arguments and a stable caller-provided idempotency_key

#### Scenario: Untrusted MCP arguments
- **WHEN** an MCP caller supplies role overrides, unknown tools, changed replay arguments or another principal's operation ID
- **THEN** the request is rejected with equivalent policy, validation or concealed-not-found behavior and no unauthorized dispatch

### Requirement: Independent human control
MCP agent credentials SHALL NOT grant approval, audit administration or direct tool/database access. Required approval SHALL remain an independently authenticated human action bound to the immutable operation. Submission SHALL never execute implicitly.

#### Scenario: MCP requests an approval-required transfer
- **WHEN** an authenticated agent proposes a transfer requiring approval and attempts execution without a human grant
- **THEN** submission records the pending request and execution cannot move funds until a separate valid human decision

### Requirement: MCP verification and delivery boundary
Milestone B SHALL preserve A's persistence, frontend and Swagger workflow, add offline contract/security tests and real Docker interoperability using an official SDK client, and remain opt-in and local. Milestone A SHALL contain no MCP runtime, SDK, remote tool connection or MCP execution.

#### Scenario: Milestone A deployment
- **WHEN** the local lab starts before B is implemented
- **THEN** no MCP service or dependency is required or started

### Requirement: Local MCP transport security
The MCP service SHALL authenticate protocol requests with a distinct generated credential, hold only the trusted AGENT API credential and reject identity/role overrides. Exact Host/Origin allowlists, DNS rebinding protection, bounded bodies, explicit HTTP timeouts, sanitized failures and managed SDK lifespan SHALL protect ingress. Static local identity SHALL be documented as distinct from production multi-user OAuth.

#### Scenario: Compose deployment
- **WHEN** the existing startup command starts the MCP service
- **THEN** it publishes only 127.0.0.1:8002, mounts no approver or PostgreSQL secrets into MCP, waits for API health, exposes readiness and preserves existing balances and operations

#### Scenario: Unauthenticated or hostile transport
- **WHEN** a client presents no valid MCP credential, a hostile Host/Origin or an oversized streamed body
- **THEN** the transport rejects it before authenticated API forwarding and exposes no tokens or rejected raw input

### Requirement: Real protocol and durable PostgreSQL evidence
An official SDK client SHALL verify initialization, discovery and invocation against actual containers without mocked protocol behavior. PostgreSQL evidence SHALL prove immutable bindings, one success and conserved balances, including replay after MCP/API restart. Existing regressions and quality gates SHALL pass before B tasks are complete. Milestone C SHALL remain unimplemented.

#### Scenario: Complete protocol workflow
- **WHEN** real Docker verification runs
- **THEN** it covers ALLOW, DENY, REQUIRE_APPROVAL, rejection before independent human approval, explicit execution, concurrent duplicate submission/execution, inspection, rejected overrides and unauthorized callers; offline tests also cover timeouts, connection failures and sanitization

#### Scenario: Approved execution survives ingress and API restart
- **WHEN** a human approves through the independent existing workflow, MCP executes and replays, then MCP and API restart
- **THEN** replay returns the persisted result, PostgreSQL retains identical bindings and one success, and balances do not change again
