# Spec Delta

## Purpose

Define the future MCP entry point for untrusted agent requests while retaining AgentGate's application authorization and explicit execution boundary.

## ADDED Requirements

### Requirement: Authenticated application ingress
In Milestone B, MCP SHALL expose bounded typed submission, operation inspection and explicit execution through existing use cases and trusted authentication. It SHALL enforce principal ownership, strict input validation, idempotency and sanitized errors with HTTP-equivalent behavior.

#### Scenario: Untrusted MCP arguments
- **WHEN** an MCP caller supplies role overrides, unknown tools, changed replay arguments or another principal's operation ID
- **THEN** the request is rejected with equivalent policy, validation or concealed-not-found behavior and no unauthorized dispatch

### Requirement: Independent human control
MCP agent credentials SHALL NOT grant approval, audit administration or direct tool/database access. Required approval SHALL remain an independently authenticated human action bound to the immutable operation. Submission SHALL never execute implicitly.

#### Scenario: MCP requests an approval-required transfer
- **WHEN** an authenticated agent proposes a transfer requiring approval and attempts execution without a human grant
- **THEN** submission records the pending request and execution cannot move funds until a separate valid human decision

### Requirement: MCP verification and delivery boundary
Milestone B SHALL preserve A's persistence and browser workflow, add fake-transport contract/security tests, and remain opt-in and local. Milestone A SHALL contain no MCP runtime, SDK, remote tool connection or MCP execution.

#### Scenario: Milestone A deployment
- **WHEN** the local lab starts before B is implemented
- **THEN** no MCP service or dependency is required or started
