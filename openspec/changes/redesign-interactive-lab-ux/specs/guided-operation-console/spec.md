# Spec Delta

## Purpose

Guide a person through proposing, independently reviewing, executing and safely replaying simulated operations using authoritative persisted state.

## ADDED Requirements

### Requirement: Coherent navigation and one active operation
The console SHALL offer Dashboard, AI Assistant, Operations and a collapsed Developer Inspector. Chat and Operations SHALL share one authoritative operation view. Recent-operation entries SHALL resume by persisted ID without duplicating actionable cards.

#### Scenario: Start and resume a journey
- **WHEN** a user starts a transfer from chat or the manual form, switches to Operations, and returns to chat
- **THEN** the same operation and its next action remain visible, with balances and recent-operation navigation available on Dashboard

### Requirement: Authoritative guided lifecycle
The console SHALL derive a five-stage stepper from persisted policy, operation and approval data. ALLOW SHALL explain authorization without execution. Pending approval SHALL offer review, approved READY SHALL offer explicit execution, and SUCCEEDED SHALL show a receipt and safe replay.

#### Scenario: Allowed transfer
- **WHEN** a user proposes an allowed transfer
- **THEN** balances remain unchanged, Execute operation is the next action, and only explicit execution advances to a stored result

#### Scenario: Approval before execution
- **WHEN** independent approval changes a pending transfer to READY
- **THEN** the console says Approved — awaiting execution and offers Execute approved transfer without dispatching automatically

### Requirement: Explicit blocked and uncertain outcomes
DENIED, REJECTED, EXPIRED, FAILED and TIMED_OUT SHALL have specific guidance. Elapsed approval deadlines SHALL disable review and execution without inventing a persisted state. Transport uncertainty SHALL block mutation until an explicit authoritative refresh; no financial request SHALL be silently retried.

#### Scenario: Denial rejection or elapsed deadline
- **WHEN** policy denies, a reviewer rejects, or the approval deadline passes
- **THEN** no active execution control is offered and the user can inspect evidence or start a new operation

#### Scenario: Lost execution response
- **WHEN** an execution response cannot be confirmed
- **THEN** the console reports an unknown outcome, retains the original ID and offers state reconciliation before any further financial action

#### Scenario: Global uncertainty guard and delayed responses
- **WHEN** an original financial outcome is unknown and chat, manual submission, new draft, approval or execution is attempted, including concurrent or delayed actions
- **THEN** all new mutations are blocked, read-only inspection remains possible, and unrelated or stale responses cannot resolve the original uncertainty

### Requirement: Deliberate independent human review
Review SHALL show the synthetic requesting-agent context, accounts, exact USD amount, original decision and deadline. Approve SHALL require deliberate confirmation. Reject SHALL remain explicit. The interface SHALL explain that human identity is separate and approval does not execute.

#### Scenario: Confirm the exact intent
- **WHEN** a reviewer opens review and confirms approval
- **THEN** only that operation ID is approved, the immutable amount remains visible, and balances remain unchanged until separate execution

### Requirement: Safe readable AI conversation
Chat SHALL distinguish unverified model text from trusted operation data, safely format messages, offer examples, show processing, disable competing submissions and explain unavailable-provider/MCP errors. Chat history SHALL be described as process-local memory.

#### Scenario: Balance question and invented success
- **WHEN** chat returns a real balance result or model prose claims a denied transfer succeeded
- **THEN** the stored balance or denied operation determines the trusted view and model prose grants no action or success

#### Scenario: Provider or MCP unavailable
- **WHEN** a provider fails or MCP retains an uncertain call
- **THEN** the user sees sanitized recovery guidance, original-call recovery where available, and manual mode without an automatic retry

#### Scenario: Chat processing finishes on every failure
- **WHEN** chat encounters a network error, timeout or unexpected provider failure
- **THEN** processing ends with a nearby sanitized failure or uncertainty explanation, original recovery identity is retained when effects are unknown, and no tool call is automatically repeated

### Requirement: Exact manual proposals
Manual entry SHALL use USD with at most two decimals, convert exactly to safe integer cents, show fixed source/destination and provide verified policy presets. Editing a draft SHALL never alter a persisted operation. Starting a new operation SHALL create a fresh intent key.

#### Scenario: Decimal input
- **WHEN** a user enters 100.01, malformed text or more than two decimal places
- **THEN** the valid submission contains 10001 cents and invalid input creates no request

### Requirement: Durable restoration and secure session recovery
Reload SHALL restore operations through persisted IDs and refresh their state. Invalid or missing IDs SHALL show helpful errors. After explicit CSRF rejection the console SHALL renew the session, preserve the operation and require a deliberate repeat action. Credentials, rejected raw input and arbitrary error text SHALL never appear in the inspector.

#### Scenario: Service restart
- **WHEN** an old session receives LAB_FORBIDDEN after services restart
- **THEN** a new session is established without replaying the rejected mutation, and operation recovery remains available even if chat memory was lost

#### Scenario: Original identity survives repeated reconciliation failures
- **WHEN** a lost submission response is followed by LAB_FORBIDDEN, session renewal failure, repeated reconciliation errors and page reload
- **THEN** the original payload, key and recovery identity remain intact, new identities are blocked, and only deliberate reconciliation reuses the original request or reads the original known operation

#### Scenario: Restoration error survives initialization
- **WHEN** a saved ID is malformed, nonexistent or unavailable during startup or reload
- **THEN** the specific sanitized restoration error remains visible with a safe restore path and is not replaced by readiness, provider or audit messages

#### Scenario: Safe replay after reload
- **WHEN** a successful operation is restored and replayed
- **THEN** the original receipt is shown and the backend applies no duplicate debit or success audit

### Requirement: Independent audit availability
The console SHALL distinguish unavailable audit evidence from uncertain financial effects. Audit failures SHALL preserve confirmed operation state and accessible continuation controls. Retrying audit retrieval SHALL be independent of mutation and financial reconciliation.

#### Scenario: Confirmed operation and failed audit read
- **WHEN** submission or inspection confirms an operation and the following audit read times out or returns an HTTP error
- **THEN** the operation stays confirmed, the audit view reports its own failure, continuation remains accessible and an independent retry can restore evidence without a financial mutation

### Requirement: Accessible responsive interaction
The console SHALL work at mobile, tablet and desktop widths without horizontal page overflow, provide visible focus, labeled controls, keyboard navigation, status announcements and text alongside semantic colors. Review cancellation SHALL restore focus. Developer details SHALL be collapsed initially.

#### Scenario: Keyboard and small screen
- **WHEN** a user navigates at 390px width or uses Tab, Enter and Escape for review
- **THEN** navigation and the next action remain available, focus stays understandable, and review can be confirmed or canceled without a pointer
