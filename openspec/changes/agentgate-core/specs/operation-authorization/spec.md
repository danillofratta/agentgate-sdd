# Spec Delta

## Purpose

Authorize untrusted agent requests for simulated financial tools and require independently authenticated human oversight when policy requires it.

## ADDED Requirements

### Requirement: Trusted identity and least privilege
The service SHALL derive principals and roles from configured bearer credentials, grant agents explicit tool and source-account allowlists, and reserve approval and global audit access for a separate approver role. Body fields SHALL NOT establish identity, role, permissions, or policy.

#### Scenario: Agent impersonates an approver
- **WHEN** an agent calls an approval or global audit endpoint, or includes an approver role in its request body
- **THEN** the endpoint returns 403 for insufficient role or 422 for forbidden fields, and no approval or transfer occurs

#### Scenario: Missing or invalid authentication
- **WHEN** a protected endpoint receives no credential or an invalid credential
- **THEN** it returns 401 without exposing configuration or invoking any tool

#### Scenario: Alternate adapter cannot bypass authorization
- **WHEN** a use-case handler is called directly with a trusted agent principal that lacks an approver role, tool permission, source ownership, or operation ownership
- **THEN** it enforces the same denial or concealed-not-found behavior as the HTTP path, without relying on route checks

### Requirement: Adapter-independent authorization invariants
Domain values and transitions SHALL enforce valid identifiers, integer USD amounts, immutable request identity, and approval lifecycle rules independently of transport validation. Policy SHALL evaluate explicit trusted facts and time without I/O; unavailable facts SHALL never imply permission.

#### Scenario: Transport validation is bypassed
- **WHEN** a non-HTTP caller attempts invalid money, an invalid identifier, changed approved arguments, a repeated approval transition, or approval consumption at expiry
- **THEN** domain invariants reject the operation without a tool call or ledger change

#### Scenario: Policy evaluation is a side-effect-free query
- **WHEN** the same trusted policy snapshot is evaluated repeatedly outside the HTTP service
- **THEN** decisions and reason codes are identical, no operation or approval is created, and no audit, database, or external side effect occurs

### Requirement: Strict bounded input
Requests SHALL accept only known fields, registered tool names, canonical account identifiers, and tool-specific typed arguments. Transfer amounts SHALL be strict positive integer cents in USD; booleans, floats, strings, unsupported currency, and same-account transfers SHALL be rejected. Bodies SHALL be limited to 16 KiB and idempotency keys to 1–64 ASCII letters, digits, underscores, or hyphens.

#### Scenario: Malicious or malformed input
- **WHEN** a caller submits unknown fields, shell or path tool names, SQL-like account identifiers, oversized strings, negative or zero amounts, boolean amounts, noninteger amounts, or unsupported currency
- **THEN** validation returns 422, or 413 for an oversized body, and no tool executes or balance changes

### Requirement: Deterministic policy decisions
The service SHALL return ALLOW for permitted balance reads and permitted transfers of 1–10,000 cents, REQUIRE_APPROVAL for permitted transfers of 10,001–100,000 cents, and DENY above 100,000 cents. Unknown accounts, disallowed tools or source accounts, insufficient funds, policy failures, or missing policy context SHALL cause DENY without execution.

#### Scenario: Exact amount boundaries
- **WHEN** an authorized agent requests funded transfers of 1, 10,000, 10,001, 100,000, and 100,001 cents between known distinct accounts
- **THEN** decisions are respectively ALLOW, ALLOW, REQUIRE_APPROVAL, REQUIRE_APPROVAL, and DENY

#### Scenario: Authorization uncertainty fails closed
- **WHEN** policy evaluation raises an exception or required identity, account, permission, or policy data is unavailable
- **THEN** the service refuses execution, exposes a stable reason code without exception detail, and records DENY when audit storage is available

#### Scenario: Tool and account permissions are enforced
- **WHEN** a valid request names a registered tool outside the agent allowlist, an unauthorized source, an unknown account, or an amount exceeding available funds
- **THEN** the decision is DENY and the ledger is unchanged

### Requirement: Durable human approval
REQUIRE_APPROVAL SHALL create a durable pending request bound to its operation ID, agent principal, canonical tool arguments, and policy version. A separate approver SHALL grant or reject it once, before its 300-second expiry. Approval SHALL authorize only that exact operation and SHALL NOT itself execute a tool.

#### Scenario: Approval then explicit execution
- **WHEN** an approver grants an unexpired pending request and its owning agent explicitly executes the operation
- **THEN** the harness revalidates current permissions, policy version, funds, and approval, records effective ALLOW with human-approval provenance, and executes at most once

#### Scenario: Rejection expiry and repeated decisions
- **WHEN** an approval is rejected, execution occurs at or after expiry, or a second approval decision is submitted
- **THEN** rejection or expiry prevents execution, and the second decision returns 409 without replacing the original decision

#### Scenario: Approval cannot authorize a changed operation
- **WHEN** another agent accesses the operation, a caller attempts to replace approved arguments, or policy version changes before execution
- **THEN** ownership access is concealed as 404, mutation is rejected, or stale-policy execution is denied respectively, with no transfer

### Requirement: Sanitized security responses
The service SHALL expose stable decision and error reason codes and SHALL exclude bearer tokens, authorization headers, raw malicious payloads, tracebacks, and configuration secrets from responses, logs, and audit records. Production startup SHALL reject absent, duplicate, or sample credentials.

#### Scenario: Secret and injection containment
- **WHEN** authentication, validation, policy, or execution fails with a credential or newline/log-injection sentinel in the input
- **THEN** captured responses, logs, and audit records contain no secret or raw injected value and preserve structured event boundaries

#### Scenario: Unsafe startup credentials
- **WHEN** the service starts without distinct non-sample agent and approver credentials
- **THEN** startup fails before accepting requests and identifies only the invalid configuration field
