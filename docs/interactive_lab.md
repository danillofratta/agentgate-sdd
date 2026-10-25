# Interactive lab — Milestone A

This local simulation adds PostgreSQL and a browser to the authorization harness.
No real funds, MCP runtime, LLM provider or external tools are involved. The one
OpenSpec change `add-interactive-lab` plans A, B and C. Only A is implemented here;
B and C require later authorization and their respective milestone branches.

## Windows startup

Install Docker Desktop with Linux containers and Compose v2. From the repository
root, run this single command in Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_lab.ps1
```

- Frontend: <http://127.0.0.1:8080>
- Swagger: <http://127.0.0.1:8001/docs>
- OpenAPI: <http://127.0.0.1:8001/openapi.json>

Port 8001 avoids an existing service on 8000; internal API traffic uses 8000.
Keep 8080 and 8001 free. Build downloads images and packages; runtime tools are
local. The API and frontend run as an unprivileged container user. Only their
IPv4 loopback ports are published. PostgreSQL has no published port and uses an
internal persistence network. The lab network permits Docker host forwarding;
it exposes no generic outbound proxy or remote tools.

The script generates three independent random secrets into ignored `.lab-secrets`
files, restricts that directory to the current Windows identity and mounts the
files read-only through Compose secrets. No token is printed, committed or
embedded in images or browser assets. Retain these files with the data volume.
Docker administrators can access container secrets. Swagger does not inject
credentials; use the browser lab for the credential-free demonstration.
`AGENTGATE_LOCAL_DEVELOPMENT=1` explicitly enables Swagger and `/accounts`;
the default API surface remains unchanged and documentation stays disabled.

## Demonstrate business behavior

1. Observe Alice and Bob balances ($10,000 each on first startup).
2. Select `$1 · Allow`, submit, then Execute. Replay returns the stored result
   without another transfer.
3. Select `$200 · Approval`, submit and observe `REQUIRE_APPROVAL` and
   `PENDING_APPROVAL`. Human Approve grants the exact operation; Execute returns
   `SUCCEEDED` with effective `ALLOW / HUMAN_APPROVED`. Original policy stays
   `REQUIRE_APPROVAL`.
4. Submit another pending operation with a new key and Reject. State becomes
   `REJECTED`; execution is blocked and balances stay unchanged.
5. Select `$1,000.01 · Deny`; observe DENY and unchanged balances.
6. Inspect status, approval expiry, paginated audit timeline and the HTTP
   inspector. It shows the last action's request/status/body, excluding bearer
   headers and CSRF values. Uncheck Current operation to see other records.
7. Reuse the same key and intent to replay submission. Changed arguments under
   the same key return 409. Generate new creates a fresh intent. Resume an
   operation by ID after restarting.
8. `get_balance` is a separately submitted and executed local tool. Balance
   cards use the approver-only read-only query, adding no audit/operation noise.
   Agent source permissions remain Alice-only. Approval expires in 300 seconds.

The human buttons represent a separate synthetic approver in a single-user
teaching interface, not production login or multi-user authorization. Host and
Origin checks, fetch metadata and session-bound CSRF prevent cross-site use.
The proxy has only fixed API methods/destinations; browser identity, URL, policy
or authorization overrides are never trusted. A future model must not receive
these credentials or human approval controls as agent tools.

## Persistence and recovery

`AGENTGATE_DATABASE` remains a SQLite path by default and accepts an explicit
`postgresql://` or `postgres://` URL. Compose uses PostgreSQL host/password-file
configuration instead of putting its password in a URL environment variable.
`dependencies.py` chooses all adapters. Six existing repository contracts and
the Unit of Work remain the application boundary. Shared hydration functions
are pure; SQL and parameter binding remain in backend adapters. PostgreSQL
schema v1 includes all current SQLite v6 fields. No automatic data copy occurs.

Command transactions use READ COMMITTED and a transaction-scoped advisory
writer lock before authoritative reads. All application writers participate,
including submission, approval, attempt allocation and recovery. This deliberate
coarse serialization matches SQLite behavior and trades throughput for simple
auditable correctness. Direct SQL writers are outside this application protocol.
Read adapters use REPEATABLE READ READ ONLY snapshots without the writer lock.

Only the UoW commits. Balances, result, approval consumption and success audit
commit together. Attempt evidence commits before dispatch. Each repository
statement refreshes its timeout against the same execution deadline. Only
classified transient locks with proven rollback retry. Entered commit failures
remain uncertain and require fresh durable reconciliation before redispatch.
Connection establishment and entered COMMIT are not hard real-time interruptible.

The named `postgres_data` volume survives stop/start, restart, rebuild and
ordinary `docker compose down`. Seeding inserts missing accounts and never
updates existing balances. Retain both volume and secrets, and back them up
before maintenance. Losing the PostgreSQL password file requires deliberate
administrator recovery: silently generating another password cannot change the
password stored in an existing database.

```powershell
docker compose stop
docker compose up -d --wait
docker compose down   # retains named data volume
```

## Verification

```powershell
uv sync --locked --python 3.12
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy --strict src
openspec validate --all --strict
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
uv run --locked python scripts/smoke_lab.py
# Optional UI QA using installed Microsoft Edge:
uv run --locked --with playwright==1.56.0 python scripts/browser_smoke.py
```

Default tests remain offline with outbound network/subprocesses blocked. Opt-in
integration tests run in a separate Compose project, on an internal network and
tmpfs PostgreSQL database. Their fixture only accepts `postgres-test` and
`agentgate_test` and blocks subprocesses. They never reset the persistent lab.
Isolation/read-only, duplicate/distinct concurrency, conservation, approval,
audit rollback, restart replay, uncertain commits, connection loss, deadline,
ownership and malicious input have independent integration cases.

The smoke script creates simulation records and transfers $201 from Alice to
Bob, then restarts PostgreSQL and API containers and checks balances, approval,
idempotency and one committed success. Repeated runs use fresh keys. It reads
no credential files and never deletes a volume. It runs outside offline Pytest.

Browser QA also creates simulation records and transfers $201. It uses installed
Edge, checks desktop and 390px mobile layouts and saves screenshots to ignored
`.lab-artifacts`. Playwright is not an application/runtime dependency. CI now
defines separate jobs for offline quality gates and real PostgreSQL/Docker smoke;
the remote jobs will first run when the changes are pushed or proposed.

The locking design follows
[PostgreSQL advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)
and [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
See [recorded verification](milestone_a_verification.md) for results and limits.
