# Spec Delta

## Purpose

Define a future conversational simulation interface whose model can propose actions but cannot authorize them or bypass AgentGate's execution safeguards.

## ADDED Requirements

### Requirement: Untrusted conversational proposals
In Milestone C, chat SHALL convert model suggestions into strictly validated proposals through authenticated MCP use cases. The LLM SHALL have no database, policy override, approval credential, arbitrary execution or direct tool dispatch capability.

#### Scenario: Prompt injection requests authorization bypass
- **WHEN** a user, model output or tool response requests bypassing policy, changing approved arguments or assuming an approver role
- **THEN** ordinary validation, ownership and approval rules reject the attempt with no unauthorized effects

### Requirement: Visible intent and human decisions
Chat SHALL show proposed arguments, policy decision, operation ID, status and explicit execution/replay outcomes. Human approval SHALL remain a separate trusted UI action unavailable to model-generated calls. Model text SHALL never be displayed as proof of committed success.

#### Scenario: Model claims an unexecuted transfer succeeded
- **WHEN** model text claims success for a pending or rejected operation
- **THEN** the interface shows authoritative stored state and no success is recorded without the execution use case

### Requirement: Controlled model configuration and testing
Milestone C SHALL use server-side explicitly configured provider secrets, bounded calls and sanitized failures. Automated tests SHALL use fake models and fake MCP transports, including adversarial output and unavailable providers. Milestone A SHALL add no LLM runtime or provider calls.

#### Scenario: Provider unavailable or malformed output
- **WHEN** a model times out or returns invalid action arguments
- **THEN** chat reports a bounded failure, leaks no secrets, and commits no fabricated operation or financial effect
