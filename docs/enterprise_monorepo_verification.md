# Enterprise monorepo verification

Change: `refactor-enterprise-monorepo`; branch: `refactor/enterprise-monorepo`.
Implementation tracking: **5/6 tasks complete**; final aggregate acceptance remains pending.
See [design and path mapping](../openspec/changes/refactor-enterprise-monorepo/design.md).

## Phase A

Locked uv sync passed on Python 3.12.14. Full offline Python suite: **1055 passed**.
Ruff lint/format passed (250 Python files), strict Mypy passed (199 source files).
Backend Docker build passed using only its own context. Strict OpenSpec: 5 passed.
Acceptance scripts relocated to `tests/e2e/`; root startup script retained.

## Phase B

Before removing Python static routes: standalone Nginx build passed, all 43 Node
behavior tests passed, base and fake-chat Compose configs passed, all five local
services healthy. Live proxy checks passed for static assets, CSP/no-store,
session cookies/CSRF, valid mutation, hostile Host/Origin/fetch-site/authorization
and forged forwarding headers. Static routes removed only after these checks.
BFF/chat/architecture: 162 passed. Disposable PostgreSQL: 17 passed.
Real HTTP lab and official MCP legacy/modern smokes passed, including independent
human approval, concurrency, immutable bindings, audit and API/MCP/PostgreSQL
restart replay. Fake-provider chat passed through real MCP/API/PostgreSQL with
BFF restart and exactly one success. Microsoft Edge manual and chat browser
acceptance passed, including approval/rejection, explicit execution, replay,
reload/resume, audit, navigation and responsive layouts (screenshots in ignored
`.lab-artifacts/`). Existing browser scripts needed synchronization with dialog
readiness and expansion of collapsed operation references; app assets are unchanged.
Actionlint passed. No real provider calls.

## Phase C

Seven enum files moved with definitions byte-equivalent after newline
normalization to the pre-refactor baseline. All canonical imports updated;
no compatibility aliases or duplicate enum classes. Genuine Value Objects and
feature schemas/requests/results retained. Focused domain/architecture/SQLite
recovery/concurrency/API lifecycle suite: **285 passed**. Seven frozen enum
serialization/identity cases and three architecture classification cases added.
Strict Mypy: 200 source files; Ruff and strict OpenSpec passed.

## Final acceptance

Final offline gates passed: **1065 Python tests**, **43 Node tests**, Ruff lint,
format (263 files), strict Mypy (200 source files), strict OpenSpec (5 changes),
all three Compose configurations and actionlint. Release-document verification
matched 42 scenarios, 87 passing node IDs, five documentation checks and 138 links.
PostgreSQL final integration: **17 passed** against disposable storage.

Source audit compared all 199 baseline runtime modules: excluding imports, only
`features/demo_lab/endpoint.py` changes AST, removing its three static handlers
and asset path. All seven enum definitions, the lockfile content and all three
browser assets match baseline after Git newline normalization. Detailed local
evidence: `.lab-artifacts/monorepo-equivalence.json`, `monorepo-paths.json`,
`monorepo-pytest.xml` and browser screenshots (ignored, never committed).

Final real HTTP/MCP smokes passed on the relocated/enum-organized images,
including modern/legacy negotiation, independent approval, concurrent execution,
immutable bindings, audit and restart replay against the original existing lab.
Final chat/browser repetition after the engine incident remains **blocked**.
The final aggregate task 4.1 stays unchecked. Phase B already demonstrated both
browser workflows and fake-provider restart/replay; final images passed real
HTTP/MCP and PostgreSQL, but their final chat/browser repetition did not finish.

## File moves and changes

| Old path | New owner/path |
| --- | --- |
| `src/agentgate/` | `backend/services/agentgate/src/agentgate/` |
| `tests/` except frontend | `backend/services/agentgate/tests/` |
| `integration_tests/` | `backend/services/agentgate/integration_tests/` |
| root `pyproject.toml`, `uv.lock`, `Dockerfile` | `backend/services/agentgate/` |
| `features/demo_lab/static/index.html` | `frontend/apps/lab-console/index.html` |
| `features/demo_lab/static/app.js`, `style.css` | `frontend/apps/lab-console/src/` |
| `tests/frontend/console.test.cjs` | `frontend/apps/lab-console/tests/console.test.cjs` |
| Python scripts in `scripts/` and two executable runners in `docs/` | `tests/e2e/` |
| seven `domain/value_objects/` enum modules | `domain/enums/` under the backend |

All **266 moved files** have verified destinations: 184 have unchanged content
and 82 have intentional edits (primarily canonical enum imports). New files add
frontend Docker/Nginx configuration, local build instructions/ignore files,
`infra/README.md`, enum package/classification/serialization guards, proxy smoke,
OpenSpec artifacts and this report. Root Compose entrypoints, startup, docs and
CI remain repository-wide. No root Python shim, shared library or new framework.

Substantive Python changes: removal of BFF static routes; BFF tests now expect
404 for those routes; architecture guards enforce enum ownership; seven fixed
serialization/identity cases cover stored values. No policy, handler, harness,
repository or persistence behavior changes. No schema/fingerprint migration.

## Dependency and security boundaries

DDD/CQRS/Vertical Slice/Hexagonal boundaries and package namespace `agentgate`
remain enforced by the architecture suite. `dependencies.py` alone composes
concrete adapters. Feature DTOs, commands/queries/results stay slice-owned;
`Principal`, `OperationRequest`, `BalanceResult` and other genuine domain values
remain Value Objects. All imports point to one canonical enum definition.

Nginx serves the browser and proxies only `/lab/*` to backend `lab-bff`; it has
no Python/uv, credentials, environment secrets or secret mounts. BFF retains
session cookies, CSRF, exact Host/Origin/fetch-site checks, server-side API/MCP
credentials and chat orchestration. Proxy preserves Host/Origin/cookies/CSRF,
clears forwarding overrides and disables upstream retries. Static/error responses
retain CSP, no-store, nosniff and no-referrer. Valid mutations and malicious
Host/Origin/CSRF/fetch-site/authorization cases were tested through real Nginx.

Human approval remains outside model tools and never executes automatically.
Runtime Harness remains the financial dispatch boundary. Tests covered immutable
approval intent, direct-handler authorization, malicious requests, idempotency,
concurrency, one audit success, rollback, uncertain commit/reconciliation and
restart replay. All actual transfers were simulation-only; no paid LLM calls.

## Docker and CI

Backend context: `backend/services/agentgate/`, owning runtime and verification
targets. Independent frontend context: `frontend/apps/lab-console/`, unprivileged
Nginx. `lab-bff` owns the former Python frontend process without a public port.
Frontend retains `127.0.0.1:8080`; API/MCP ports stay 8001/8002. Compose project
name, original `postgres_data` name, networks and `.lab-secrets/*` paths stay
unchanged. The fake-provider overlay targets only BFF and mounts `tests/e2e/`.

CI now selects the backend project explicitly, runs relocated tests and standalone
Node tests, validates Compose/proxy isolation, and exercises real manual/MCP and
fake-provider chat/browser workflows. Browser dependencies are verification-only;
no Python is installed to build the frontend. Actionlint passed locally; hosted
GitHub Actions has not run because no push is authorized.

## Environment incident and remaining deployment risks

During final repetition, Docker began reporting **no containers, images or
volumes** in both `desktop-linux` and `default` contexts. The previously observed
`agentgate-lab_postgres_data` was absent. Cause is undetermined. Commands in this
session did not delete images or volumes; only disposable integration containers
were stopped/removed with `docker compose -f compose.test.yaml down` (no `-v`).
The original volume was not recreated or replaced with a seeded empty database.
A separate project `agentgate-monorepo-acceptance` and distinct volume were
created for further acceptance. Docker then returned HTTP 502 from its own
container-inspection API during startup, before the isolated run could finish.
Original persisted data availability requires separate recovery or confirmation
of an intentional environment cleanup. The Docker failure is unresolved; subsequent calls reported the engine named pipe
missing. The isolated project may remain partially started. No Docker Desktop reset, prune,
volume deletion or original-volume reseeding was attempted.

Other compatibility changes: local Python tooling must use the service directory
or root `--project` commands; undocumented old enum import paths change. Browser
HTTP and MCP contracts, enum strings and persistence mapping remain compatible.
BFF restarts clear in-memory chat sessions, so uncertain operations require
inspection of their original durable ID before proposing a new transfer.
Real provider interoperability remains opt-in and was deliberately not tested.

## Git handoff

Branch: `refactor/enterprise-monorepo`. Nothing staged or committed; no push,
merge or archive. Git currently reports 20 modified tracked files, 266 deleted
old paths and 282 untracked new paths. The deletions/new paths represent unstaged
moves; staging during a later review will let Git display rename detection.
The lockfile is relocated without dependency changes. Existing secret files are
retained and ignored. Disposable test storage is separate from the original lab.

