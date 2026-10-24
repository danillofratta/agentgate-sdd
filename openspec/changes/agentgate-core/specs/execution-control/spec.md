# Spec Delta

## Purpose

Keep simulated tool execution bounded, idempotent, and auditable even when requests race, storage fails, or authorization becomes uncertain.

## ADDED Requirements

### Requirement: Simulation-only registered tools
The runtime SHALL expose only registered balance lookup and simulated transfer tools over local seeded USD accounts. It SHALL perform no real transaction, subprocess execution, arbitrary code evaluation, dynamic tool import, outbound network access, LLM call, or MCP call.

#### Scenario: Local-only execution
- **WHEN** the complete runtime test suite runs with outbound network access blocked and subprocess invocation forbidden
- **THEN** balance lookup, transfer, approval, and audit scenarios pass entirely against temporary local storage

### Requirement: Explicit command execution boundary
Requesting, approving, and executing operations SHALL use separate command handlers; only execution SHALL dispatch tools. Executing even a read-only balance tool SHALL be a command because it persists operation/result/audit evidence. Inspection queries SHALL NOT implicitly execute an operation.

#### Scenario: Request approval and inspection cannot dispatch
- **WHEN** an operation is requested, approved, or inspected without an explicit execute command
- **THEN** no tool is dispatched, no balance changes, and approval is not consumed

### Requirement: Side-effect-free inspection queries
Operation and audit inspection SHALL use query handlers with read-only ports over the same durable data used by commands. Queries SHALL enforce ownership/role checks and SHALL NOT change balances, operation state, approvals, expiry state, results, or durable audit records.

#### Scenario: Repeated reads preserve state
- **WHEN** an owning agent reads an operation or an approver lists audit records repeatedly, including after approval expiry
- **THEN** the queries return authorized views without any durable state change or implicit expiry write

### Requirement: Durable principal-scoped idempotency
Operation creation SHALL require an idempotency key scoped to the authenticated agent. The same key and canonical request SHALL return the same operation and stored terminal result; a different request under that key SHALL return 409. These guarantees SHALL survive concurrent requests and process restart.

#### Scenario: Concurrent identical requests
- **WHEN** two concurrent submissions use one agent, key, and transfer payload and both attempt execution
- **THEN** they identify one operation and produce at most one committed debit, credit, successful result, and success audit event

#### Scenario: Conflict restart and principal isolation
- **WHEN** a key is reused with different arguments, the service restarts and receives an identical replay, or another agent uses the same key
- **THEN** the conflict returns 409, the replay returns the stored operation/result, and the other agent has an independent key namespace without access to the first operation

### Requirement: Authorization at execution boundary
Execution SHALL recheck current authorization and consume any required approval in the same atomic boundary as the simulated transfer and its success audit. DENY, pending, rejected, expired, and stale-policy operations SHALL NOT invoke a tool. Terminal operations SHALL NOT execute again.

#### Scenario: State changes after authorization
- **WHEN** funds or permissions change after initial authorization but before execution
- **THEN** execution denies an operation that is no longer permitted and does not consume its approval or alter balances

#### Scenario: Pending and terminal execution
- **WHEN** execution is requested for an unapproved operation or an already successful operation
- **THEN** the first returns 409 without dispatch and the second returns its stored result without a second dispatch

### Requirement: Atomic financial simulation and audit
Each transfer SHALL atomically debit and credit integer cents, preserve total funds and nonnegative balances, and persist its terminal result and success audit. Failure of any write SHALL roll back all effects. Failure to persist required authorization evidence SHALL prevent execution.

#### Scenario: Audit write failure
- **WHEN** success-audit persistence fails after proposed balance updates
- **THEN** both balance changes, approval consumption, and the success result roll back, and the service returns a sanitized unavailable response

#### Scenario: Concurrent insufficient funds
- **WHEN** distinct operations concurrently request transfers whose sum exceeds the source balance
- **THEN** only transfers funded at their atomic execution boundary succeed and the source never becomes negative

#### Scenario: Adapter boundaries preserve one transaction
- **WHEN** command orchestration uses repository, tool, and audit adapters through the unit-of-work boundary and a failure is injected before commit
- **THEN** account entities, approval consumption, operation result, and audit writes roll back together; no adapter commits independently or requires asynchronous event delivery

### Requirement: Bounded execution and controlled retries
Each execution SHALL dispatch at most one logical tool, use a 2-second monotonic deadline, and make at most two transaction attempts. Only explicitly classified transient storage-lock failures proven to have rolled back SHALL be retried, with one delay of at most 50 ms within the original deadline. Authorization, validation, unknown failures, and expired approval SHALL NOT be retried.

#### Scenario: Deadline prevents a late write
- **WHEN** an injected clock reaches the deadline before execution commits
- **THEN** execution rolls back, returns TIMED_OUT, records a sanitized terminal outcome when storage permits, and no delayed activity can subsequently modify balances

#### Scenario: Retry budget and classification
- **WHEN** the first attempt fails with a rolled-back storage-lock error and the second succeeds, both attempts fail, or a nonretryable error occurs
- **THEN** attempt counts are respectively two, two, and one, with no more than one transfer and no deadline reset

#### Scenario: Uncertain commit is not retried blindly
- **WHEN** a commit outcome cannot be confirmed
- **THEN** execution stops, returns an unavailable response, and reconciles the durable operation before any later dispatch; it never assumes a rollback

### Requirement: Durable sanitized audit access
The service SHALL record authenticated decisions, approval decisions, dispatch attempts, and terminal outcomes using event IDs, UTC timestamps, principal IDs, operation IDs, tool names, policy versions, reason codes, and attempt numbers where applicable. Audit access SHALL be approver-only, paginated with at most 100 events per response, and expose no mutation endpoint.

#### Scenario: Lifecycle evidence survives restart
- **WHEN** an operation requires approval, receives approval, and succeeds, followed by a restart
- **THEN** the approver can retrieve correlated ordered events proving the original decision, approver identity, execution attempts, and one committed success

#### Scenario: Audit least privilege and bounded output
- **WHEN** an agent requests global audit data or an approver requests a page larger than 100
- **THEN** the agent receives 403 and the invalid page size receives 422, with no unbounded result set
