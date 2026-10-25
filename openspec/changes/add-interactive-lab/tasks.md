# Tasks

One change, three milestone deliverables. C is authorized on the existing feat/llm_and_chat branch by explicit user clarification, with no new branches, commits, pushes or archive. One Pull Request per milestone.

## 1. Milestone A — Persistent interactive local lab

- [x] 1.1 Implement complete PostgreSQL schema, six repository adapters and deadline-aware Unit of Work; preserve SQLite and composition boundaries. Verify independent integration cases for isolation, concurrent duplicate/distinct execution, balance conservation, idempotency/replay, restart, rollback and uncertain-commit recovery; document backend selection and locking.
- [x] 1.2 Add protected opt-in local Swagger and approver-only read-only balance inspection, with authorization, read-only and default-docs regression tests and API documentation.
- [x] 1.3 Deliver the polished frontend and constrained credential-holding proxy for decisions, explicit human approve/reject, execution/replay, status/audit and sanitized HTTP inspection. Verify workflow and hostile Host/Origin/CSRF/override cases and document the local synthetic identity boundary.
- [x] 1.4 Deliver Docker Compose with persistent PostgreSQL 16, health checks, loopback-only ports, generated file secrets and one-command Windows startup. Verify Docker smoke workflow and API/database restart persistence; document startup, URLs, recovery and stop without data deletion.
- [x] 1.5 Run all 925 existing regressions plus new tests, PostgreSQL integration and Docker smoke tests, locked dependency sync, Ruff check/format, strict Mypy and strict OpenSpec validation. Record concrete results, demonstrated business workflow and remaining limitations; stop after A.

## 2. Milestone B — MCP server integration

- [x] 2.1 Implement the official pinned stable MCP Python SDK with Streamable HTTP at loopback port 8002, explicit SDK lifespan, distinct inbound credential and server-side AGENT API credential. Expose exactly request_operation, get_operation and execute_operation through the existing FastAPI HTTP API; enforce bounded strict schemas, exact Host/Origin allowlists, DNS rebinding protection, timeouts and sanitized errors. Extend Compose and existing startup with persistent storage, generated secret, API dependency and MCP readiness; document endpoint, real SDK client and local identity limits.
- [x] 2.2 Verify real MCP initialization, discovery and invocation, policy parity, ownership, invalid inputs, idempotency, human-only approval, immutable bindings, concurrent PostgreSQL execution, one financial effect and durable replay after MCP/API restart. Add offline protocol/transport and failure/security tests, run all A regressions and quality gates plus real Docker client verification, and record evidence in docs/milestone_b_verification.md. Preserve frontend, Swagger and all financial guarantees; stop before C.

## 3. Milestone C — LLM agent and chat

- [ ] 3.1 Implement server-side configured model gateway and chat interface proposing validated operations through MCP, displaying authoritative intent/decision/status and explicit execution/replay. Verify fake-provider and fake-MCP workflows, bounded failures and secret isolation; document configuration on the single C branch.
- [ ] 3.2 Verify prompt injection, malformed output, provider outages, ownership, changed approved arguments and fabricated success cannot bypass policy or human approval. Run A/B regressions and document the complete three-milestone workflow and trust boundaries before completing C.

## Workflow follow-up

- Review the coherent A/B/C deliverables without creating another branch or committing/pushing.
- Stop after C. Archive only on a separate explicit request.
