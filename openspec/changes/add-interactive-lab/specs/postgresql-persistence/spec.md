# Spec Delta

## Purpose

Preserve AgentGate's transactional simulation guarantees across a selectable durable PostgreSQL backend and the existing SQLite backend.

## ADDED Requirements

### Requirement: Complete selectable persistence
The service SHALL support PostgreSQL 16 for accounts, operations, approvals, execution results, audit and principal-scoped idempotency in one database per deployment, preserving SQLite and existing application contracts.

#### Scenario: Backend parity
- **WHEN** the same authenticated submission, approval, execution and inspection workflow runs on either backend
- **THEN** policy decisions, lifecycle transitions, results and sanitized errors have the same meaning and require explicit execution

### Requirement: Atomic and isolated execution
PostgreSQL commands SHALL serialize conflicting state changes and commit balances, result, approval consumption and success audit atomically. Reads SHALL use consistent read-only snapshots. Balances SHALL remain nonnegative integer cents with conserved total funds.

#### Scenario: Concurrent duplicate execution
- **WHEN** concurrent callers submit the same principal/key/request and execute the resulting operation
- **THEN** one operation and at most one transfer and committed success exist, with identical replayed results

#### Scenario: Independently competing operations
- **WHEN** distinct operations compete for funds or transfer in opposite directions
- **THEN** committed balances conserve total funds, no balance is negative, and authorization uses current locked facts

#### Scenario: Isolation and read-only enforcement
- **WHEN** a transaction holds uncommitted writes and a separate inspection transaction reads state or attempts a write
- **THEN** it observes only committed consistent data and the read-only transaction rejects writes

### Requirement: Durable replay and recovery
Restart SHALL preserve balances, approval decisions, audit and idempotency. Proven rollback SHALL permit only the existing bounded transient-lock retry; uncertain commits SHALL reconcile before any later dispatch. Audit failure SHALL prevent committed financial effects.

#### Scenario: Restart replay
- **WHEN** the API and PostgreSQL containers restart after a successful approved transfer
- **THEN** resubmission and execution return the stored operation/result without another debit or success event

#### Scenario: Failure and reconciliation
- **WHEN** audit writes fail, a lock exhausts the deadline, a connection is lost before commit, or commit acknowledgment is uncertain
- **THEN** effects roll back or durable state is reconciled, errors expose no SQL or credentials, and execution never blindly redispatches
