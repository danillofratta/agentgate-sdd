# Spec Delta

## Purpose

Deliver the local simulation lab as independently buildable browser and backend applications while preserving its authorization and recovery guarantees.

## ADDED Requirements

### Requirement: Independent application delivery
The browser application SHALL build and run without Python, backend source or credentials. The backend SHALL build without browser source. Existing API, BFF JSON and MCP contracts SHALL remain stable.

#### Scenario: Build each application independently
- **WHEN** either application's own build context is provided
- **THEN** its image builds without source or tools from the other application

### Requirement: Same-origin protected browser lab
The browser SHALL remain accessible at `http://127.0.0.1:8080` with same-origin `/lab/*` requests, session cookies, CSRF validation, exact Host/Origin validation, restrictive CSP and secure response headers. Proxying SHALL preserve validation inputs and SHALL NOT trust browser-supplied forwarding or authorization overrides.

#### Scenario: Legitimate browser mutation
- **WHEN** the browser sends its session cookie, matching Origin and valid CSRF token through the frontend
- **THEN** the BFF processes the request under the existing server-side identity

#### Scenario: Hostile browser request
- **WHEN** a request has a hostile Host, Origin, fetch site, authorization override or invalid CSRF token
- **THEN** access is rejected without business effects or credential disclosure

### Requirement: Financial and recovery compatibility
The delivered lab SHALL retain independent human approval, explicit financial execution, deterministic policy, atomic persistence and audit, immutable approval bindings, idempotency and restart replay. Approval SHALL NOT execute an operation. Existing persistent volumes and secret locations SHALL be retained.

#### Scenario: Approved transfer and replay after restart
- **WHEN** an approved simulated transfer executes and is replayed after the API, BFF or MCP restarts
- **THEN** stored results remain compatible and the transfer has exactly one financial effect

#### Scenario: AI-assisted human workflow
- **WHEN** a fake model proposes a transfer through actual local MCP/API/persistence
- **THEN** human approval remains separate and the transfer requires an explicit execution action
