# Design

## Context

See proposal.md. The baseline is a single root Hatch/uv project with PostgreSQL and SQLite adapters. `demo_lab/endpoint.py` serves three static files and JSON routes; `LabSecurity` accepts exactly loopback port 8080 and same-origin mutations. Compose currently calls the Python credential-holding BFF `frontend`. Offline Node tests read assets directly; architecture tests locate the package relative to their Python project. Main specs are empty; all four existing completed active changes remain historical baseline contracts.

## Goals / Non-Goals

Goals: independent build contexts, unchanged browser behavior, traceable relocation, inward imports and verified persistence compatibility. Non-goals: new business rules, database migration, new JS framework, generic libraries, workspace package manager, real financial effects or paid provider calls.

## Decisions

### Ownership and current-to-target mapping

| Current | Target | Notes |
| --- | --- | --- |
| `src/agentgate/` | `backend/services/agentgate/src/agentgate/` | Import namespace unchanged |
| `tests/` except frontend | `backend/services/agentgate/tests/` | Unit/in-process integration and architecture tests |
| `integration_tests/` | `backend/services/agentgate/integration_tests/` | Opt-in local PostgreSQL integration, own image verification target |
| `pyproject.toml`, `uv.lock`, `Dockerfile` | `backend/services/agentgate/` | Own README and Docker ignore; immutable dependency lock |
| `src/agentgate/features/demo_lab/static/index.html` | `frontend/apps/lab-console/index.html` | Asset references adjusted only |
| `.../static/app.js`, `.../static/style.css` | `frontend/apps/lab-console/src/` | Behavior unchanged |
| `tests/frontend/console.test.cjs` | `frontend/apps/lab-console/tests/console.test.cjs` | Node built-in runner, no packages |
| `scripts/browser*smoke.py`, `scripts/smoke*.py`, `scripts/mcp_client.py`, `scripts/verify_chat_app.py` | `tests/e2e/` | Cross-process protocol/browser acceptance and fake-provider factory |
| `docs/run_final_e2e_acceptance.py`, `docs/verify_release.py` | `tests/e2e/` | Executable acceptance belongs with tests |
| `domain/value_objects/{approval_decision,approval_state,decision,operation_state,reason,role,tool}.py` | `domain/enums/` within relocated project | Exact enum definitions preserved, canonical imports updated |
| root Compose variants, `.github/`, `docs/`, `scripts/start_lab.ps1`, `openspec/` | same | Repository-wide assets |
| deployment infrastructure (none separate today) | `infra/README.md` | Ownership documentation only, no speculative resources |

### Process and proxy boundary

Use the existing backend Dockerfile for API, MCP and renamed `lab-bff`. Add an independent Nginx frontend context with no Python or secrets. Root Compose retains project name `agentgate-lab`, named `postgres_data`, secret definitions and API/MCP published ports; only Nginx publishes 8080. BFF listens internally on 8080. Proxy only `/lab/`, preserve `$http_host`, cookies, Origin, fetch metadata and CSRF, suppress untrusted forwarding headers, disable automatic upstream retries for financial requests and keep bounded timeouts. Preserve BFF `LabSecurity` unchanged. Serve only the three known assets; no SPA wildcard or proxy destination input. Apply existing CSP/no-store/nosniff/referrer headers to static/error responses. Host allowlist protects static content too. Health checks use explicit allowed Host. The fake-provider overlay targets only BFF, mounted from `tests/e2e/`.

Alternatives: Python static serving prevents independent frontend deployment; a new JS framework adds unnecessary tooling; weakening allowed hosts to the Docker service name would dilute browser protections. Preserve the original host instead.

### Dependency boundaries and classification

All existing DDD/CQRS/Hexagonal rules continue under the relocated Python root. Domain depends only on domain and standard library, enum modules have one class each, no aliases duplicating enum identity. Genuine dataclass values (`Principal`, `OperationRequest`, `BalanceResult`, inspections, IDs, snapshots and audit facts) remain Value Objects regardless of their names. Feature HTTP DTOs remain in `models.py`, CQRS requests/results in their owning slices. Repositories stay in domain, gateways in application ports, concrete adapters in infrastructure; only root DI constructs them. No feature imports sibling slices, no dispatch outside execution harness. Frontend communicates only with the BFF JSON boundary. Cross-application tests may exercise actual local adapters, while default Python tests keep network/process bans.

Extend executable architecture guards to enforce enum placement and independent build contexts. Update contributor paths and current architecture docs; historical verification counts are historical evidence, not results of this change.

### Tooling

Run locked Python commands with `--project backend/services/agentgate` from root or from that project. Service README makes packaging self-contained. CI uses explicit project paths and standalone Node tests. Keep root OpenSpec commands and Compose. No root Python shim that silently recreates package ownership. All repository verification scripts explicitly resolve repository and service roots.

## Risks / Trade-offs

- Host rewriting breaks CSRF/session flows -> preserve exact original Host and test the real proxy with positive/hostile requests.
- Split process deployment can accidentally leak secrets -> frontend mounts none; inspect Compose and verify secret sentinels absent from assets/image.
- Renaming BFF loses in-memory chat state -> document deliberate restart/session recovery; durable business state is unchanged.
- Older launch commands and source links become stale -> update current docs/scripts/CI, document working directory change.
- Enum import changes may affect undocumented Python imports -> update every repository reference; public HTTP/MCP and persisted string values stay unchanged, no persisted Python pickles exist.
- Docker tests depend on local engine -> record actual results and leave unmet verification tasks pending if unavailable.

## Migration Plan

A: relocate Python, adjust backend contexts and references while keeping its static serving; run focused/full Python and architecture gates plus OpenSpec. B: build/verify Nginx and proxy with existing static routes still present, then remove only those Python routes; run frontend, security, PostgreSQL and real local browser/protocol smoke. C: move exact enum definitions, rewrite imports and enforce organization; run domain/recovery and final full quality/deployment checks. Record per-phase results in `docs/enterprise_monorepo_verification.md`. No database schema edits or data resets. Rollback deploys prior images with the same volume/secrets; stop containers without `-v`. Do not claim completion until all required verification passes.
