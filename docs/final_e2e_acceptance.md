# Final end-to-end acceptance — task 7.2

**Passed on 2026-10-24, 21:37:17–21:37:19 America/Sao_Paulo**
(2026-10-25 00:37:17–00:37:19 UTC). Only acceptance documentation, its
reproducible runner, a focused concurrency test, traceability and the task 7.2
checkbox changed. Application code, credentials configuration, policies, schema,
dependencies and CI were not changed. Task 7.1 was already checked complete;
its [quality report](final_quality_gates.md) records the prerequisite verification.

## Environment and reproducibility

Source HEAD before this increment: `d2f0f2b0ae528c054f0d96cc970ea247e11db278`.
The working tree was clean before adding these acceptance artifacts. The existing
local image `agentgate-quality:task71-final`, ID
`sha256:364ee17204ff968586e7a86a15f65d366b1021a31d9fd55e0502cd50e84b6a0b`,
supplied Python 3.12.14, uv 0.12.5, SQLite 3.40.1 and OpenSpec 1.14.3.
Current `src`, `tests`, `docs` and `openspec` were copied into `/workspace`.
`git diff f4e82111e4ef845e8a9e9082b97b2ba56a0304be HEAD -- src` was empty:
runtime source matches the image's task 7.1 source.

The container used `--network none`, no host mounts, dropped capabilities and
`no-new-privileges`. Inspection returned:

```text
NetworkMode: "none"
Tmpfs: {"/tmp":"rw,nosuid,nodev,size=256m"}
Mounts: []
Interfaces: [(1, 'lo')]
IPv4 routing table: header only, no routes
```

No port was published. Both HTTP client and real Uvicorn processes ran inside
this network namespace, using `http://127.0.0.1:8000`. No external service was
contacted. The tmpfs choice follows task 7.1's documented storage isolation;
the database is a real SQLite file, retained across both server processes.

The [acceptance runner](../tests/e2e/run_final_e2e_acceptance.py) runs **outside Pytest**,
preserving the suite's socket/subprocess guards. It generates distinct 48-byte
URL-safe synthetic tokens in memory, supplies them only through child process
environment, disables proxy use, and never prints headers or token values.
Its explicit seed command is the README command with offline uv resolution:

```text
uv run --project backend/services/agentgate --offline --locked python -m agentgate.infrastructure.persistence.seed --database <fresh temporary SQLite path>
```

Seeding initialized schema v6 and both balances at 1,000,000 cents. The final
run's database was `/tmp/agentgate-e2e-dlhxu4ou/acceptance.sqlite3`, outside
project files. Approval and execution completed within the 300-second deadline.

Two additional unexecuted fixtures were created before server startup through
the existing request handler: a 1-cent operation belonging to `principal-other`,
and an owning agent's pending approval created with a supplied clock 600 seconds
in the past. The fixed adapter exposes only one agent credential; these fixtures
let real HTTP test foreign ownership and already elapsed expiry without adding
another authentication mode or waiting. No HTTP dependencies were overridden.

## Real server lifecycle

Each launch used the documented factory command:

```text
uv run --project backend/services/agentgate --offline --locked uvicorn agentgate.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

| Evidence | First process | Restarted process |
| --- | --- | --- |
| uv launcher PID | 256 | 262 |
| Actual Uvicorn PID | **260** | **266** |
| Startup log | `Started server process [260]` | `Started server process [266]` |
| Readiness | `Application startup complete.` and authenticated GET /audit, HTTP 200, simulation true | Same |
| Shutdown | SIGTERM sent to PID 260 | SIGTERM sent to PID 266 after verification |
| Exit evidence | `Application shutdown complete.`; `Finished server process [260]`; `/proc/260` absent; launcher reaped | Corresponding lines and `/proc/266` absent; launcher reaped |

The uv launcher returned 143 for each forwarded SIGTERM. Graceful application
shutdown is established by Uvicorn's completed lifecycle logs and process absence,
rather than interpreting that launcher code as a startup failure. The second
process started only after the first had exited. It reused the exact database
path and synthetic authentication configuration; no reseeding occurred.

## HTTP decisions, approval and execution

Unique random idempotency keys were used for the three submissions.

| Amount (cents) | Persisted decision / initial state | Operation ID |
| --- | --- | --- |
| 1 | ALLOW / READY | `c7a249fe-bf3a-4139-a301-d0dd74b26e49` |
| 100,001 | DENY / DENIED | `6386b1bb-e9f9-48de-b1c3-093ca0d68895` |
| 10,001 | REQUIRE_APPROVAL / PENDING_APPROVAL | `e64b9f76-a7d0-47d9-a762-ad07ef0469cf` |

All submissions returned 201; SQLite confirmed each original decision. Submission
left balances unchanged and produced zero dispatch/success events. The DENY
operation had no approval row and execution returned 403. Pending execution
returned 409. Agent self-approval returned 403. These steps produced no transfer.

The trusted approver's `POST /operations/{id}/approval` returned 200 / GRANTED.
SQLite verified matching operation ID, principal, canonical fingerprint, policy
version and creation timestamp, with approver `principal-approver`. Approval
still left both balances at 1,000,000 and dispatch/success counts at zero.

The owning agent then executed with an empty request body. HTTP 200 returned:

```json
{
  "state": "SUCCEEDED",
  "simulation": true,
  "decision": "REQUIRE_APPROVAL",
  "effective_decision": "ALLOW",
  "effective_reason": "HUMAN_APPROVED",
  "result": {
    "source_account_id": "acct-alice",
    "destination_account_id": "acct-bob",
    "amount_cents": 10001,
    "currency": "USD"
  }
}
```

This excerpt omits unchanged envelope fields. Original policy evidence remained
REQUIRE_APPROVAL / APPROVAL_REQUIRED / v1. The approval became CONSUMED.

| Account | Initial cents | Final cents | Change |
| --- | --- | --- | --- |
| acct-alice | 1,000,000 | **989,999** | -10,001 |
| acct-bob | 1,000,000 | **1,010,001** | +10,001 |
| Total | 2,000,000 | **2,000,000** | 0 |

There was exactly one SUCCEEDED operation, one committed OPERATION_DISPATCHED
event and one committed OPERATION_EXECUTED event across the database. Together
with the exact result and balance deltas, this establishes one intended effect.
The ALLOW operation remained unexecuted.

## Replay, audit and read-only proof

Repeated execution returned the complete original execution envelope. Equivalent
submission with the original key and reversed JSON argument order returned 200,
the same operation ID and persisted result. A changed amount under that key
returned 409. Repeated approval returned 409. None changed the committed snapshot.

Real `GET /operations/{id}` returned the stored result, simulation marker and
CONSUMED approval for owner and approver. The agent received concealed 404 for
the foreign fixture, while the approver could inspect it. `GET /audit` returned
403 for the agent and 401 without authentication; `limit=101` returned 422.
Approver pagination returned ordered structured events and an empty final page.

The approved operation's lifecycle was identical before and after restart:

| Audit ID | Type | Decision / reason | Additional evidence |
| --- | --- | --- | --- |
| 5 | OPERATION_REQUESTED | REQUIRE_APPROVAL / APPROVAL_REQUIRED | principal-agent, v1 |
| 6 | APPROVAL_DECIDED | APPROVE / HUMAN_APPROVED | principal-approver, matching fingerprint |
| 7 | OPERATION_ATTEMPTED | ALLOW / EXECUTION_ATTEMPT | attempt 1 |
| 8 | OPERATION_DISPATCHED | ALLOW / DISPATCH_AUTHORIZED | same operation/fingerprint |
| 9 | OPERATION_EXECUTED | SUCCEEDED / EXECUTION_SUCCEEDED | same operation/fingerprint |

The canonical fingerprint was
`c6a52481697b40230b4223e9b35a21c6daa289bd9b066e4090e44da42abcb0c7`.
Every audit event matched the HTTP field allowlist. A malformed sentinel request
returned sanitized 422. All collected responses, both server logs, evidence JSON
and live SQLite bytes were checked for both tokens, authorization/header strings,
raw rejected sentinel values and tracebacks; none appeared.

The runner used SQLite's backup API to retain transactionally consistent full
database snapshots, including schema and sqlite_sequence, with integrity and
foreign-key checks. It hashed the complete canonical `iterdump()` from each
backup. Before/after each set of three repeated query rounds, it also kept a
read-only monitoring connection open and checked `PRAGMA data_version` unchanged,
detecting commits even if final row contents would match.

All these snapshots had the same SHA-256:

```text
013047e694973a9ed9b4b7a57dd09c6fa157a5596e9bf0314535ddbe679826d0
```

They include committed state, after replays/conflicts, before/after GET rounds,
before/after restarted GET rounds, and final stopped state. Thus repeated queries
performed no durable writes, appended no audit, and did not persist implicit
expiry: the already elapsed fixture remained PENDING. The backup-file byte hash
is not the reported hash; the comparison covers schema and all persisted rows.

After the actual restart, HTTP returned the same operation/result and correlated
approval/audit evidence. Repeated execution and submission replayed the original
committed result. Snapshot, balances, one dispatch and one success stayed unchanged.

## Concurrency review and verification

Existing separate guarantees remain in `test_request_storage.py` (identical
submissions) and `test_concurrent_execution_recovery.py` (same-operation execution,
competing funds and commit failure/reopen). The added focused test is
`tests/infrastructure/test_overlapping_submission_execution.py::test_submission_overlaps_execution_and_both_callers_replay_one_transfer`.

It uses real request/execute handlers, file-backed SQLite, separate UoWs, a fake
clock and a counting wrapper around the existing local tool registry. Two caller
pipelines submit the same key/payload and both execute. Events hold the first
execution at dispatch while the second submission handler enters its factory;
the second factory waits for the first execution to commit before opening its
connection. Assertions establish overlapping handler calls, stable identity and
result, one creation, one tool invocation, one debit/credit and one success event.
Replay execution leaves the full snapshot unchanged. There are no timing sleeps.

This explicitly exercises one controlled combined interleaving. It does not
claim simultaneous SQLite BEGIN contention, every possible schedule, or an HTTP
load test; the preexisting independent concurrency/lock tests provide complementary
coverage. No runtime lock budget, retry or fixture guard was changed.

All required gates ran offline in the isolated container:

| Command | Exit | Result |
| --- | --- | --- |
| `uv sync --offline --locked --python 3.12` | 0 | 29 resolved, 28 installed packages checked |
| `uv run --project backend/services/agentgate --offline --locked pytest --junitxml=/tmp/acceptance-pytest.xml` | 0 | **925 passed**, 1 warning, 10.95 s; includes all 123 architecture tests and the added overlap test |
| `uv run --project backend/services/agentgate --offline --locked ruff check --config backend/services/agentgate/pyproject.toml backend/services/agentgate tests/e2e` | 0 | All checks passed |
| `uv run --project backend/services/agentgate --offline --locked ruff format --check --config backend/services/agentgate/pyproject.toml backend/services/agentgate tests/e2e` | 0 | 227 files already formatted |
| `uv run --project backend/services/agentgate --offline --locked mypy --strict backend/services/agentgate/src` | 0 | No issues in 151 source files |
| `openspec validate --all --strict` | 0 | 1 change passed, 0 failed |

`uv run --project backend/services/agentgate --offline --locked python backend/services/agentgate/tests/e2e/verify_release.py --junit /tmp/acceptance-pytest.xml`
also passed: 42 scenarios, 87 exact passing test references, five documentation
check definitions and 75 relative links. The JUnit report was exported beside
the retained acceptance evidence.

The existing Starlette/HTTPX deprecation warning remains. This increment reuses
the previously built locked environment; it does not claim another clean install,
hosted CI execution, abrupt crash/power-loss test or production certification.

## Reproduce and retain evidence

With the task 7.1 image available (its build is documented in the quality report),
run from the current checkout in PowerShell:

```powershell
docker run -d --name agentgate-acceptance-reproduce --network none --tmpfs /tmp:rw,nosuid,nodev,size=256m --cap-drop ALL --security-opt no-new-privileges agentgate-quality:task71-final sleep infinity
docker cp src agentgate-acceptance-reproduce:/workspace/
docker cp tests agentgate-acceptance-reproduce:/workspace/
docker cp docs agentgate-acceptance-reproduce:/workspace/
docker cp openspec agentgate-acceptance-reproduce:/workspace/
docker exec agentgate-acceptance-reproduce uv sync --offline --locked --python 3.12
docker exec agentgate-acceptance-reproduce uv run --project backend/services/agentgate --offline --locked python tests/e2e/run_final_e2e_acceptance.py
```

The last command prints sanitized evidence JSON with a fresh temporary directory
and actual PIDs. Inspect its exit status. That directory contains the database,
consistent snapshots, `evidence.json`, `http-checks.json` and two server logs.
The runner stops both servers, leaves evidence available and never saves tokens.
Run the gate commands above with the same `docker exec` prefix; the standalone
runner is deliberately not collected by Pytest.

Export evidence **before** removing the disposable container. Docker cp on this
host could not read tmpfs paths directly, so the successful export copied the
directory to `/workspace/.pytest_cache/acceptance-evidence` inside the container
first, then used `docker cp` to a fresh host temporary directory. Retained evidence
for this run is under:

```text
C:\Users\danil\AppData\Local\Temp\agentgate-acceptance-72-f8b3d9f46baa4aeaa7009a0178e6238c\acceptance-evidence
```

This untracked local evidence survives container removal. Synthetic account and
request data are retained locally; no working credential, database or backup is
committed. The report and runner provide durable repository evidence independent
of the disposable storage. Task 7.2 is complete for review; nothing was archived.
