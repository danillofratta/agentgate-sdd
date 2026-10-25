# Milestone A verification

Verified locally on 2026-10-24 (America/Sao_Paulo), on the existing branch.
The `add-interactive-lab` proposal, design, four capability deltas and milestone
tasks cover A/B/C. Only A is implemented. No branch was created, no commit or
push was made, and neither OpenSpec change was archived.

## Results

| Check | Observed result |
| --- | --- |
| `uv sync --locked --python 3.12` | Passed; local Python 3.12.14 |
| `uv run --locked pytest` | 943 passed: all 925 original tests unchanged, plus 18 lab tests; 69.19 seconds |
| `uv run --locked ruff check .` | Passed |
| `uv run --locked ruff format --check .` | Passed |
| `uv run --locked mypy --strict src` | Passed; 175 source files |
| `openspec validate --all --strict` | Both changes passed |
| PostgreSQL integration Compose | 16 passed; PostgreSQL 16.15, Python 3.12.15; 1.97 seconds |
| Docker startup | All three containers healthy; only 127.0.0.1:8080 and 127.0.0.1:8001 published; PostgreSQL not published |
| Docker HTTP workflow and container restart smoke | Passed decisions, approval/rejection, explicit execution, replay, conserved balances, security checks and database/API restart durability |
| Real Edge headless UI | Passed ALLOW, DENY, human approve/reject, exact submitted arguments, execution/replay, audit and HTTP inspector; no JavaScript errors |
| Responsive UI | Desktop 1440px and mobile 390px checked; no mobile horizontal overflow; screenshots saved in ignored `.lab-artifacts` |

Both Pytest suites emit one existing Starlette warning about its deprecated
httpx TestClient integration. It does not fail any test; this increment does not
change the existing HTTP testing dependency to address that upstream warning.

## Independently verified PostgreSQL behavior

`integration_tests/test_postgres.py` has separate tests for:

- Duplicate concurrent submission/execution: one operation, transfer and success.
- Distinct competing operations: current funds and nonnegative conserved balances.
- Opposite-direction transfers: no lost update, conserved total funds.
- Read isolation: uncommitted data invisible and a repeatable committed snapshot.
- Read-only transaction enforcement by PostgreSQL itself.
- Approval/rejection and idempotency conflict/replay, including effective human authorization.
- Competing human decisions: exactly one decision and audit event commits.
- Audit-write failure: balances, result and approval consumption roll back.
- Restarted application components: durable idempotency and stored results survive.
- Lost commit acknowledgment after success: fresh durable reconciliation returns success.
- Uncertain attempt without commit: no redispatch within the failed call; a later
  explicit execution is safe.
- Connection loss before commit: no partial balance effect.
- Writer lock timeout: classified transient error only after confirmed rollback.
- Deadline before commit: rollback with no delayed effect.
- Principal key isolation and direct-handler authorization.
- Malicious fields/amounts and sanitized output.
- Expiry and repeated reads without implicit query mutations.

The real-container smoke independently restarts PostgreSQL and the API after an
approved transfer and checks the same stored result, balances, idempotency key,
approval evidence and exactly one committed success event. The persistent named
volume and generated secrets are retained throughout stop, rebuild and restart.

## Scenario traceability

| A capability/scenario | Evidence |
| --- | --- |
| Backend parity | Existing 925 SQLite tests; PostgreSQL `test_policy_approval_rejection_replay_and_idempotency` |
| Concurrent duplicates | `test_concurrent_duplicate_submission_and_execution` |
| Independent competing operations | `test_distinct_concurrent_executions_conserve_funds`, `test_opposite_transfers_conserve_total_without_lost_updates` |
| Isolation and read-only enforcement | `test_read_isolation_consistent_snapshot_and_read_only` |
| Restart replay | `test_restart_components_preserve_replay`, `scripts/smoke_lab.py` |
| Failure and reconciliation | Audit failure, connection loss, deadline, lock and two uncertain-commit tests |
| First startup/subsequent restart | Windows startup executed; healthy Compose and restart smoke |
| Interactive decisions/approval/replay | `test_lab_full_workflow_and_secret_isolation`, `test_lab_deny_reject_and_balance_read`, real browser script |
| Proxy abuse | Parameterized context/override tests, CSRF session binding and fixed-path tests |
| Local/default Swagger | `test_local_swagger_and_host_protection`; original API surface test unchanged |
| B/C requirements | Planning only; their tracked tasks remain unchecked and no MCP/LLM runtime was added |

## Limits and handoff

- No remaining Milestone A implementation blocker was observed.
- This is a single-user synthetic local demo, with intentionally serialized
  writes. It is not production identity management or a throughput benchmark.
- PostgreSQL's entered COMMIT and connection setup are not hard real-time
  interruptible. Unknown acknowledgment remains uncertain until reconciliation.
- The smoke tests intentionally leave simulation history and changed balances.
  Fresh startup seeds only missing accounts; it never restores demo balances.
- Browser verification used installed Edge through the optional pinned
  Playwright script because the integrated browser execution tool was unavailable.
- CI job definitions were added; remote GitHub execution is pending the user's
  later commit/push. Local equivalent commands passed.
- No SQLite data migration, MCP runtime or LLM runtime is included. B and C remain
  future work in this same change.

Startup and maintenance commands are in [interactive_lab.md](interactive_lab.md).

## Files changed

The inventory below includes the pre-existing OpenSpec scaffold retained for
this change, all new files and all modified tracked files. Ignored generated
secrets, database volumes, bytecode and browser screenshots are excluded.

- `.dockerignore`
- `.github/workflows/ci.yml`
- `.gitignore`
- `Dockerfile`
- `README.md`
- `compose.test.yaml`
- `compose.yaml`
- `docs/architecture.md`
- `docs/interactive_lab.md`
- `docs/milestone_a_verification.md`
- `docs/persistence.md`
- `integration_tests/conftest.py`
- `integration_tests/test_postgres.py`
- `openspec/changes/add-interactive-lab/.openspec.yaml`
- `openspec/changes/add-interactive-lab/design.md`
- `openspec/changes/add-interactive-lab/proposal.md`
- `openspec/changes/add-interactive-lab/specs/agent-chat/spec.md`
- `openspec/changes/add-interactive-lab/specs/interactive-lab/spec.md`
- `openspec/changes/add-interactive-lab/specs/mcp-ingress/spec.md`
- `openspec/changes/add-interactive-lab/specs/postgresql-persistence/spec.md`
- `openspec/changes/add-interactive-lab/tasks.md`
- `pyproject.toml`
- `scripts/browser_smoke.py`
- `scripts/smoke_lab.py`
- `scripts/start_lab.ps1`
- `src/agentgate/application/ports/demo_api_gateway.py`
- `src/agentgate/components.py`
- `src/agentgate/dependencies.py`
- `src/agentgate/features/demo_lab/__init__.py`
- `src/agentgate/features/demo_lab/endpoint.py`
- `src/agentgate/features/demo_lab/static/app.js`
- `src/agentgate/features/demo_lab/static/index.html`
- `src/agentgate/features/demo_lab/static/style.css`
- `src/agentgate/features/list_accounts/__init__.py`
- `src/agentgate/features/list_accounts/endpoint.py`
- `src/agentgate/features/list_accounts/handler.py`
- `src/agentgate/features/list_accounts/models.py`
- `src/agentgate/features/list_accounts/query.py`
- `src/agentgate/infrastructure/gateways/local_demo_api_gateway.py`
- `src/agentgate/infrastructure/persistence/postgres_database.py`
- `src/agentgate/infrastructure/persistence/postgres_session.py`
- `src/agentgate/infrastructure/persistence/postgres_unit_of_work.py`
- `src/agentgate/infrastructure/repositories/audit_mapper.py`
- `src/agentgate/infrastructure/repositories/operation_inspection_mapper.py`
- `src/agentgate/infrastructure/repositories/operation_mapper.py`
- `src/agentgate/infrastructure/repositories/postgres_account_read_repository.py`
- `src/agentgate/infrastructure/repositories/postgres_account_repository.py`
- `src/agentgate/infrastructure/repositories/postgres_approval_repository.py`
- `src/agentgate/infrastructure/repositories/postgres_audit_read_repository.py`
- `src/agentgate/infrastructure/repositories/postgres_audit_repository.py`
- `src/agentgate/infrastructure/repositories/postgres_operation_read_repository.py`
- `src/agentgate/infrastructure/repositories/postgres_operation_repository.py`
- `src/agentgate/infrastructure/repositories/sqlite_account_read_repository.py`
- `src/agentgate/infrastructure/repositories/sqlite_audit_read_repository.py`
- `src/agentgate/infrastructure/repositories/sqlite_operation_read_repository.py`
- `src/agentgate/infrastructure/repositories/sqlite_operation_repository.py`
- `src/agentgate/infrastructure/security/settings.py`
- `src/agentgate/lab.py`
- `src/agentgate/main.py`
- `src/agentgate/transport/configure.py`
- `src/agentgate/transport/lab_security.py`
- `tests/api/test_interactive_lab.py`
- `uv.lock`
