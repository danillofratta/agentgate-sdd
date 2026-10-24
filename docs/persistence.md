# SQLite persistence and recovery

AgentGate uses one SQLite database for commands and queries. CQRS separates
responsibilities, not databases: there is no projection, replication pipeline,
mediator, event bus, or event sourcing. Set `AGENTGATE_DATABASE` to the same path
used for explicit seeding and recovery. `dependencies.py` wires adapters into
handler constructors; HTTP endpoints never open storage.

## Ownership and transactions

| Owner | Responsibility |
| --- | --- |
| `domain/repositories/` | Narrow `AccountRepository`, `OperationRepository`, `ApprovalRepository`, `AuditRepository`, and operation/audit read contracts using domain types only |
| `application/ports/` | `RequestUnitOfWork` and `RequestUnitOfWorkFactory` define transaction access and lifetime; policy, credential, clock and ID ports are separate technical boundaries |
| `infrastructure/repositories/` | SQLite implementations, parameterized SQL, row/domain mapping; no independent commit |
| `infrastructure/persistence/` | Connection, schema validation/migration, explicit seed and `SqliteUnitOfWork`; no business authorization |
| Command handlers | Authorize intent, coordinate domain rules and repositories, explicitly commit required business state and audit together |
| Query handlers | Authorize inspection through read contracts; return feature results without durable writes |

`RequestOperationHandler` stores an immutable operation, a pending approval when
required, and its request audit in one UoW. `BEGIN IMMEDIATE` serializes writers.
All repositories share that connection. Only the UoW commits; leaving it without
commit, or failing an audit write, rolls back the transaction and closes it.
Request submission never dispatches a tool or changes balances.

`EvaluatePolicyQuery` evaluates supplied facts without storage.
`GetOperationQuery` and `ListAuditQuery` read the same database through read-only
SQLite URI connections with `query_only=ON`. Operation and approval reads share
one read transaction. Repeated reads never persist expiry, change balances,
consume approval, recompute results, or append audit. An expired pending approval
can therefore still be stored as PENDING. Invoking a balance tool through the
future execution lifecycle is a command because it must persist result/audit.
Approval/execution handlers and their transactional updates are later tasks.

Adapters reconstruct typed IDs, integer USD money, enums, UTC timestamps and
immutable entities/snapshots. Canonical request JSON and its SHA-256 fingerprint
must agree. Read mapping checks approval bindings and stored result shape/state;
invalid data raises sanitized `StorageUnavailable`. SQL rows never enter handlers
or domain. Query results are feature-owned DTOs, not persistence contracts.

## Schema and lifecycle

`PRAGMA user_version` versions storage independently of policy version `v1`.
Initialization runs atomically and validates the complete expected application
schema, including rejecting unexpected tables, views, triggers or columns.

| Storage version | Meaning |
| --- | --- |
| 0, empty database | Create the current v2 schema |
| 0, nonempty database | Reject; never infer or reset a schema |
| 1 | Validate the legacy schema, add nullable `operations.result_json`, advance to 2 atomically |
| 2 | Validate and reopen without resetting data |
| Any other version or mismatched schema | Fail closed without seeding or destructive repair |

`accounts` holds IDs and nonnegative integer balances. `operations` holds the
principal, idempotency key, canonical request, fingerprint, original decision and
reason, policy version, UTC creation time, state and nullable result JSON.
`UNIQUE(principal_id, key)` preserves each principal's namespace across restart
and restoration. Identical canonical requests replay the operation; changed
requests under that key conflict. Keep these columns when backing up.
`approvals` binds operation, principal, fingerprint, policy and the creation/expiry
times. `audit_events` holds ordered integer IDs and sanitized request evidence;
preserve `sqlite_sequence` as well as application tables.

Original policy decisions remain immutable: ALLOW starts READY, DENY starts
DENIED and REQUIRE_APPROVAL starts PENDING_APPROVAL. The domain permits
PENDING_APPROVAL → READY/REJECTED/EXPIRED and READY →
SUCCEEDED/DENIED/EXPIRED/FAILED/TIMED_OUT. Terminal states have no outgoing edge.
The domain approval graph permits PENDING → GRANTED/REJECTED/EXPIRED and
GRANTED → CONSUMED/EXPIRED, with supplied time and binding checks. Expiry is
creation plus 300 seconds; the exact boundary is expired.

Current persistence writes only initial operation states and PENDING approvals;
the schema explicitly restricts approval status to PENDING. It does not yet store
approver decisions or consumption metadata. The operation reader can hydrate
supported lifecycle states and typed stored success results; test fixtures supply
such results without implementing execution. A SUCCEEDED row requires a result;
other states reject a non-null result. Request repository lookup currently maps
initial states only: recovery tests do not claim terminal command replay is
implemented. Future approval/execution tasks must evolve schema and adapters.

## Seeding and sensitive data

`uv run --locked python -m agentgate.infrastructure.persistence.seed --database agentgate.sqlite3`
explicitly inserts missing `acct-alice`/`acct-bob` at 1,000,000 cents each using
`INSERT OR IGNORE`. It preserves existing balances and other stored data. Normal
initialization does not seed. Do not seed during recovery: missing accounts are
evidence to investigate rather than silently replace.

Persist only validated structured tool arguments, IDs and stable codes. Never
store bearer tokens, authorization headers, raw rejected input, exception text
or configuration secrets. Audit contains event ID/type, operation/principal IDs,
tool, decision/reason, policy version and UTC time; arguments and amounts remain
on the operation rather than being copied into audit. Current durable events are
OPERATION_REQUESTED only; typed domain facts alone are not committed evidence.

The host, clock, database administrator and credential holders are trusted. Local
audit is neither tamper-proof nor externally witnessed. An administrator can edit
or replace the database, and restoring an older backup discards newer history.
Total storage failure can prevent durable audit: fail closed, never claim an
event was recorded. No asynchronous publisher repairs missing evidence.
Backups contain the same sensitive account/request/result data as the source,
including possible deleted-page remnants. Restrict filesystem access and use
host-managed encrypted storage as needed; do not publish backups or dump rows
into logs. Redaction is an allowlist at write time, not backup sanitization.

## Safe backup and recovery procedure

Use only a trusted local backup and its matching application revision. Preserve
that revision and the backup's schema version in an operator record without
credentials. SQLite integrity checks cannot authenticate a malicious backup.
Keep the original backup immutable and retain the previous database for rollback.

1. Stop the local service and all writers, close their connections, and record
   the recovery point. Use fresh paths for the backup and recovery candidate;
   never overwrite a source, existing backup, or active database. Do not copy an
   open `.sqlite3` file alone: committed data can be in its WAL.
2. Open the source read-only (`Path(source).resolve().as_uri() + '?mode=ro'`,
   `uri=True`). Use stdlib `sqlite3.Connection.backup` into a fresh database,
   closing both handles with `contextlib.closing`. This copies a consistent
   committed SQLite snapshot, including WAL content and schema version, rather
   than a collection of table dumps. Do not use an uncommitted writer as source.
3. Validate the backup read-only: `PRAGMA integrity_check` must return exactly
   `[('ok',)]`; `PRAGMA foreign_key_check` must return no rows. A missing input
   must fail rather than create an empty database. On failure discard only the
   disposable candidate, leave the live database/backup untouched, and report a
   stable unavailable error without exception text or rejected contents.
4. Restore by using the same backup API from the immutable backup into another
   fresh candidate. Run both checks there, then call
   `initialize(candidate, seed=False)` from the matching application revision.
   Initialization validates compatibility and may migrate v1 to v2 **on this
   candidate only**. Never initialize the backup or live database as a probe.
   Reject corrupt/incompatible backups before any promotion; do not reset their
   version or strip unknown schema objects to force acceptance.
5. Reopen the candidate through existing operation/audit readers and a UoW.
   Compare operations, approval bindings/deadlines, ordered audit IDs, results,
   balances, principal/key/fingerprint pairs and schema version with the recorded
   recovery point. Use bounded audit pages. Do not execute operations to verify
   recovery. An old backup cannot recover transactions committed after its cut.
6. With the service still stopped and all handles closed, select the verified
   candidate via `AGENTGATE_DATABASE` and restart the matching application.
   Keep each database in its own clean directory so stale `-wal`/`-shm` sidecars
   from a different database cannot be reused. Retain the previous database and
   its sidecars together; do not replace a file under active connections. If
   startup or inspection fails, stop and select that preserved database with
   its matching application revision. No destructive automatic reset is used.

The disposable test procedure is executable with
`uv run --locked pytest tests/infrastructure/test_sqlite_recovery.py`.
It reuses the backup API, schema initializer, UoW and read adapters; exercises
WAL and uncommitted changes, repeat reopen, data preservation, principal-scoped
idempotency, corruption and incompatible schema rejection. It adds no runtime
maintenance endpoint or dependency. Existing transactional persistence tests
cover audit-failure rollback and nonresetting seed behavior.
