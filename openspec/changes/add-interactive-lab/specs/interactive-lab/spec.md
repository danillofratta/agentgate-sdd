# Spec Delta

## Purpose

Provide a persistent local browser environment for inspecting AgentGate's simulation and security decisions without handling bearer credentials in the browser.

## ADDED Requirements

### Requirement: Reproducible local deployment
A single Windows PowerShell command SHALL start Docker Compose with FastAPI, PostgreSQL 16 and the browser lab. Published services SHALL bind only host loopback. A named data volume SHALL survive ordinary stop, restart and rebuild. Startup SHALL seed missing demo accounts without resetting existing balances.

#### Scenario: First startup and subsequent restart
- **WHEN** a user runs the startup command on a clean checkout and later repeats it after a transfer
- **THEN** health checks succeed, the frontend is available, and previous balances and operations survive

### Requirement: Explicit interactive workflow
The browser SHALL show Alice and Bob balances, submit operations, display ALLOW/DENY/REQUIRE_APPROVAL, offer separate human approve/reject actions, explicitly execute or replay, inspect operation status and paginated audit, and inspect sanitized HTTP request/response details.

#### Scenario: Decisions approval and replay
- **WHEN** the user submits transfers of 100, 20000 and 100001 cents, approves or rejects pending requests, executes and replays
- **THEN** the lab shows each decision and lifecycle outcome, one committed approved transfer, unchanged balances on rejection/denial, and correlated audit events

### Requirement: Credential isolation and constrained proxy
The local demo proxy SHALL hold distinct randomly generated synthetic agent and approver credentials server-side. It SHALL expose only fixed API workflows, never arbitrary URLs, SQL, headers or roles. It SHALL reject untrusted Host/Origin, cross-site requests and missing CSRF protection on mutations. Secrets SHALL be absent from browser data, HTTP inspection, logs and source control.

#### Scenario: Cross-site or arbitrary proxy abuse
- **WHEN** a hostile origin, DNS rebinding host, missing CSRF header, caller-supplied upstream URL or authorization override targets the proxy
- **THEN** it is rejected without forwarding an authenticated request or exposing credentials

### Requirement: Local development documentation
Swagger and OpenAPI SHALL be disabled by default and enabled only with explicit local development configuration protected by allowed local hosts. Automated regression, PostgreSQL integration and Docker smoke verification SHALL document outcomes and limitations.

#### Scenario: Default and local Swagger
- **WHEN** the default app or explicitly configured local app is started
- **THEN** the default exposes no documentation endpoints and the local app exposes usable Swagger/OpenAPI without embedding credentials
