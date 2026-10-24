# AgentGate

A Python 3.12+ modular monolith demonstrating DDD, CQRS, Vertical Slice,
Hexagonal Architecture, and an agent authorization harness. All financial data
is simulated. No external LLM, MCP, network tool, or transaction integration exists.

## First increment

Only `POST /operations` is available. It records a policy decision, a pending
approval request when required, and an atomic audit event. It never runs a tool
or moves funds. Approval decisions, execution, operation inspection, and audit
listing are future increments. The OpenSpec task list tracks the complete MVP;
partially implemented tasks stay unchecked.

## Setup and verification

Install Python 3.12+ and uv 0.12.5+. The committed `uv.lock` pins all direct and
transitive dependencies; installation downloads packages, tests/runtime need no network.

```powershell
uv sync --locked --python 3.12
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy --strict src
openspec validate --all --strict
```

Equivalent commands after activating `.venv` are `python -m pytest`,
`python -m ruff check .`, `python -m ruff format --check .`, and
`python -m mypy --strict src`. Architecture tests run as part of Pytest.

## Local demonstration

Set `AGENTGATE_AGENT_TOKEN` and `AGENTGATE_APPROVER_TOKEN` to distinct,
random, URL-safe tokens of at least 32 characters in your environment. Generate
each with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
There are no default credentials. Do not paste credentials into committed files
or logs. `AGENTGATE_DATABASE` optionally selects a SQLite path (default
`agentgate.sqlite3`). Initialize and explicitly seed the same path before the demo:

```powershell
uv run --locked python -m agentgate.infrastructure.persistence.seed --database agentgate.sqlite3
uv run --locked uvicorn agentgate.main:create_app --factory --host 127.0.0.1
```

Seeding creates `acct-alice` and `acct-bob`, each with 1,000,000 USD cents,
and preserves existing balances. The demo agent owns `acct-alice` and may request
`get_balance` or `simulate_transfer`. The approver cannot submit agent operations.
The approver credential is validated now but has no endpoint in this increment.

Example request (supply your token as a bearer credential and `demo-1` as the
`Idempotency-Key` header):

```json
{"tool":"simulate_transfer","arguments":{"source_account_id":"acct-alice","destination_account_id":"acct-bob","amount_cents":10001,"currency":"USD"}}
```

For known, permitted, funded accounts: 1–10,000 cents returns `ALLOW`,
10,001–100,000 returns `REQUIRE_APPROVAL`, and larger values return `DENY`.
Balance requests use `{"tool":"get_balance","arguments":{"account_id":"acct-alice"}}`.
Reads require ownership too. Unknown accounts, disallowed tools/sources, missing
policy facts, and policy exceptions deny. Input rejects floats, booleans, strings
for amounts, same-account transfers, unknown fields, invalid IDs/keys, and bodies
over 16 KiB. API schemas become immutable domain values; direct handler callers
cannot bypass invariants or role checks.

New submissions return 201, identical principal-scoped replays return 200 with the
same operation, and changed payloads under an existing key return 409. No replay
creates another audit event. Errors use sanitized codes: 401 `UNAUTHENTICATED`,
403 `FORBIDDEN`, 413 `BODY_TOO_LARGE`, 422 `INVALID_INPUT`,
409 `IDEMPOTENCY_CONFLICT`, and 503 `STORAGE_UNAVAILABLE`. Decisions have separate
stable policy reason codes. Credentials, raw rejected inputs, and tracebacks
are excluded from application responses/logs/audit. Default validation output is replaced.

## Architecture and trust

Domain entities (Account, Operation, pending Approval), immutable values, and pure
policies use only the standard library. `RequestOperationCommand/Handler` owns
submission. The internal `EvaluatePolicyQuery/Handler` is its pure policy dependency,
not an exposed slice. Domain repository Protocols isolate persistence; application
ports isolate credentials, clock, and identity generation. `dependencies.py` is the only concrete wiring
root; handlers use constructor injection and routes call handlers directly.
One SQLite transaction stores the immutable request, approval, and decision audit.
No mediator, event bus, event sourcing, or separate CQRS database is used.

Each domain Entity, Value Object, and Repository contract has a matching snake_case
module. Repository contracts live in `domain/repositories`; implementations live in
`infrastructure/repositories`. Persistence ports use
`Repository` (including local audit storage), the credential boundary uses
`CredentialGateway`, and future event publishing uses `EventPublisher` only when
needed. Each feature lives under `features/<name>`, with its `endpoint.py`,
`models.py`, `command.py` or `query.py`, `handler.py`, and `result.py` when applicable.
HTTP schemas may share the feature `models.py`; handlers remain framework-free.
`main.py` only bootstraps FastAPI and registers feature routers. Architecture tests
enforce these conventions.

The host, database administrator, and configured credential holders are trusted.
This demo is local-only; it provides neither remote IAM nor tamper-proof audit.
Policy input is server-derived, never taken from identity/role fields in request
bodies. A future inbound LLM/MCP adapter must submit through the same handlers
with trusted principal context. External side-effecting tools require separately
specified cancellation/idempotency; nothing here authorizes them.
