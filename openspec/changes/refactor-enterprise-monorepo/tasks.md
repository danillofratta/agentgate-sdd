# Tasks

## 1. Phase A — Backend relocation

- [x] 1.1 Relocate the Python project, tests, locked metadata and Dockerfile; update packaging, backend Compose contexts, scripts, CI and current documentation. Verify locked sync, complete Python tests and independent backend build; preserve data/secret paths and record phase results.
- [x] 1.2 Update executable architecture/path checks and contributor instructions for the relocated project; verify architecture tests, Ruff, strict Mypy and strict OpenSpec validation before phase B.

## 2. Phase B — Independent frontend

- [x] 2.1 Extract vanilla assets and Node tests; deliver independent Nginx image and exact same-origin proxy, split credential-holding lab-bff in all Compose variants. Verify image build, Node tests, Compose configs, live assets and valid/hostile proxied session requests before removing Python static routes.
- [x] 2.2 Remove only old Python static-serving routes after frontend verification; adapt BFF tests and cross-application acceptance scripts under tests/e2e, update CI and documentation. Verify full BFF/chat/security regressions, PostgreSQL integration, real browser human workflow and fake-provider MCP chat without paid calls; record phase results.

## 3. Phase C — Domain type organization

- [x] 3.1 Move seven exact enum definitions to domain/enums, rewrite every cross-layer import, retain genuine Value Objects/DTOs/CQRS roles and add classification guards. Verify domain, architecture, persistence/restart/replay tests and serialization compatibility; document classification and phase results.

## 4. Final integrated verification

- [ ] 4.1 Run locked full Python suite, all frontend tests, lint/format, strict Mypy, all Compose configurations, PostgreSQL integration, live frontend/BFF/API/MCP smoke, fake-model chat and browser approval, restart/replay regressions, workflow validation and strict OpenSpec. Record concrete evidence, path mapping, security checks, limitations and current Git status in the delivery report. Leave any unmet acceptance tasks pending.

## Workflow follow-up

- Review changes on refactor/enterprise-monorepo. No commit, push, merge, archive, paid model calls or volume deletion is authorized.
