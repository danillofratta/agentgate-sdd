# Tasks

One change, three milestone implementation branches. A uses the current branch. B and C each use one later branch only when separately authorized. No per-task branches, commits, pushes or archive in this session.

## 1. Milestone A — Persistent interactive local lab

- [x] 1.1 Implement complete PostgreSQL schema, six repository adapters and deadline-aware Unit of Work; preserve SQLite and composition boundaries. Verify independent integration cases for isolation, concurrent duplicate/distinct execution, balance conservation, idempotency/replay, restart, rollback and uncertain-commit recovery; document backend selection and locking.
- [x] 1.2 Add protected opt-in local Swagger and approver-only read-only balance inspection, with authorization, read-only and default-docs regression tests and API documentation.
- [x] 1.3 Deliver the polished frontend and constrained credential-holding proxy for decisions, explicit human approve/reject, execution/replay, status/audit and sanitized HTTP inspection. Verify workflow and hostile Host/Origin/CSRF/override cases and document the local synthetic identity boundary.
- [x] 1.4 Deliver Docker Compose with persistent PostgreSQL 16, health checks, loopback-only ports, generated file secrets and one-command Windows startup. Verify Docker smoke workflow and API/database restart persistence; document startup, URLs, recovery and stop without data deletion.
- [x] 1.5 Run all 925 existing regressions plus new tests, PostgreSQL integration and Docker smoke tests, locked dependency sync, Ruff check/format, strict Mypy and strict OpenSpec validation. Record concrete results, demonstrated business workflow and remaining limitations; stop after A.

## 2. Milestone B — MCP integration (future implementation)

- [ ] 2.1 Implement opt-in authenticated MCP ingress translating bounded typed requests into existing submission, inspection and explicit execution use cases. Verify fake-transport contracts, principal isolation, policy parity, invalid arguments and idempotent replay; document local startup and protocol surface on the single B branch.
- [ ] 2.2 Verify agents cannot approve, override policy, access repositories or dispatch tools directly; cover independent human approval, failure sanitization and PostgreSQL concurrency through MCP. Run A regressions and update security/architecture documentation before completing B.

## 3. Milestone C — LLM agent and chat (future implementation)

- [ ] 3.1 Implement server-side configured model gateway and chat interface proposing validated operations through MCP, displaying authoritative intent/decision/status and explicit execution/replay. Verify fake-provider and fake-MCP workflows, bounded failures and secret isolation; document configuration on the single C branch.
- [ ] 3.2 Verify prompt injection, malformed output, provider outages, ownership, changed approved arguments and fabricated success cannot bypass policy or human approval. Run A/B regressions and document the complete three-milestone workflow and trust boundaries before completing C.

## Workflow follow-up

- Review the coherent A deliverable without creating another branch or committing/pushing.
- Implement B and C only after separate authorization. Archive only on a separate explicit request.
