# Proposal

## Why

AgentGate's simulation safeguards are already executable, but exploring them requires manual API calls and SQLite inspection. A persistent local lab will make decisions, independent approval, execution, and replay visible, and provide a controlled foundation for future MCP and LLM demonstrations.

## What Changes

- Milestone A: PostgreSQL 16 adapters for all existing repository contracts and the Unit of Work, preserving SQLite and the existing HTTP/handler behavior; local Docker Compose, opt-in Swagger, a polished browser lab, credential-holding demo proxy, PowerShell startup, integration and smoke tests.
- Milestone B (implemented): official stable Python MCP SDK and a separate authenticated Streamable HTTP server calling the existing FastAPI API, preserving explicit execution, ownership, policy, human approval and replay; real SDK Docker verification and bounded transport security.
- Milestone C (current authorized implementation): an LLM proposal/chat interface using the MCP boundary, with no authorization authority, direct database access, or approval credentials.
- Keep one coherent deliverable and Pull Request per milestone under this single change. C is authorized on the existing feat/llm_and_chat branch by explicit user clarification; do not create branches, commit, push or archive.
- Explicitly supersede the earlier SQLite-only deployment restriction with one selected database per deployment. PostgreSQL network traffic is local persistence, not an external tool integration. Existing offline tests remain offline; opt-in integration tests target disposable local PostgreSQL only.

## Capabilities

### New Capabilities

- `postgresql-persistence`: durable transactional simulation with adapter parity, isolation, replay, concurrency, and recovery.
- `interactive-lab`: loopback-only Docker environment, server-side synthetic credentials, browser workflow, local Swagger, and reproducible verification.
- `mcp-ingress`: authenticated MCP-to-FastAPI adapter for existing application use cases (B).
- `agent-chat`: untrusted LLM proposals and chat through authorized MCP use cases (C).

### Modified Capabilities

None in `openspec/specs` (currently empty). The active `agentgate-core` change is the baseline and remains untouched. Its authorization, execution, architecture, and regression requirements continue to apply, except for the explicitly described database selection and opt-in local integration tests.

## Impact

Adds Psycopg, PostgreSQL schema/adapters, composition selection, local HTTP transport protection, demo proxy/frontend, Docker configuration and scripts. Preserves the existing 925 tests, domain policy, lifecycle, approval binding, two-second execution budget, atomic audit and results, and SQLite adapter. No real financial transfers, MCP runtime, LLM runtime, or external tool dispatch in A.
