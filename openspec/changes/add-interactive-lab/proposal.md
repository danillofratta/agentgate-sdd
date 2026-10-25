# Proposal

## Why

AgentGate's simulation safeguards are already executable, but exploring them requires manual API calls and SQLite inspection. A persistent local lab will make decisions, independent approval, execution, and replay visible, and provide a controlled foundation for future MCP and LLM demonstrations.

## What Changes

- Milestone A: PostgreSQL 16 adapters for all existing repository contracts and the Unit of Work, preserving SQLite and the existing HTTP/handler behavior; local Docker Compose, opt-in Swagger, a polished browser lab, credential-holding demo proxy, PowerShell startup, integration and smoke tests.
- Milestone B (planning only now): authenticated MCP ingress for the same use cases, preserving explicit execution, ownership, policy, human approval, and replay.
- Milestone C (planning only now): an LLM proposal/chat interface using the MCP boundary, with no authorization authority, direct database access, or approval credentials.
- Use exactly three implementation branches, one per milestone, under this single change. Implement A on the current branch; do not create branches, commit, push, or archive in this increment.
- Explicitly supersede the earlier SQLite-only deployment restriction with one selected database per deployment. PostgreSQL network traffic is local persistence, not an external tool integration. Existing offline tests remain offline; opt-in integration tests target disposable local PostgreSQL only.

## Capabilities

### New Capabilities

- `postgresql-persistence`: durable transactional simulation with adapter parity, isolation, replay, concurrency, and recovery.
- `interactive-lab`: loopback-only Docker environment, server-side synthetic credentials, browser workflow, local Swagger, and reproducible verification.
- `mcp-ingress`: future authenticated MCP adapter for existing application use cases (B).
- `agent-chat`: future untrusted LLM proposals and chat through authorized MCP use cases (C).

### Modified Capabilities

None in `openspec/specs` (currently empty). The active `agentgate-core` change is the baseline and remains untouched. Its authorization, execution, architecture, and regression requirements continue to apply, except for the explicitly described database selection and opt-in local integration tests.

## Impact

Adds Psycopg, PostgreSQL schema/adapters, composition selection, local HTTP transport protection, demo proxy/frontend, Docker configuration and scripts. Preserves the existing 925 tests, domain policy, lifecycle, approval binding, two-second execution budget, atomic audit and results, and SQLite adapter. No real financial transfers, MCP runtime, LLM runtime, or external tool dispatch in A.
