# Human approval lifecycle walkthrough

Run the task 4.3 walkthrough from the repository root:

```powershell
uv sync --locked --python 3.12
uv run --locked pytest tests/infrastructure/test_human_approval_walkthrough.py -v
uv run --locked pytest tests/infrastructure/test_durable_approval_expiry.py -v
```

Each case uses an isolated, seeded temporary SQLite file and an injected
`FakeClock`. Existing request, policy, approval and query handlers use the existing
SQLite UoW and read adapters. This is a handler-level demonstration; the
[README](../README.md#http-demo) also covers the implemented approval HTTP route.
No credentials, service process, real-time
sleeps or external services are needed. The offline fixture blocks outbound
connections and subprocesses; architecture tests enforce tool dispatch placement.

## Distinct statuses and evidence

The original policy decision stays `REQUIRE_APPROVAL`, reason
`APPROVAL_REQUIRED`, version `v1`. Human approval does not rewrite it to `ALLOW`.
Operation status and approval status are separate:

| Step | Operation status | Approval status | Durable audit evidence |
| --- | --- | --- | --- |
| Submit funded 10,001-cent transfer | PENDING_APPROVAL | PENDING | OPERATION_REQUESTED / REQUIRE_APPROVAL / APPROVAL_REQUIRED |
| Grant at creation + 30 seconds | READY | GRANTED | APPROVAL_DECIDED / APPROVE / HUMAN_APPROVED |
| Reject at creation + 30 seconds, in another database | REJECTED | REJECTED | APPROVAL_DECIDED / REJECT / HUMAN_REJECTED |
| Reopen either decided database | Preserved | Preserved | Same two ordered records and event IDs |
| Call pure `Approval.expire(now)` at creation + 300 seconds | EXPIRED in returned domain snapshot | EXPIRED in returned domain snapshot | No new durable event; snapshot is not persisted |
| Query an expired-by-time request before the expiry command | PENDING_APPROVAL or READY in storage | PENDING or GRANTED in storage | Existing request/decision records only |
| Internal expiry command at or after original deadline | EXPIRED in storage | EXPIRED in storage | APPROVAL_EXPIRED / EXPIRED / APPROVAL_EXPIRED |
| Reopen or repeat expiry command | EXPIRED | EXPIRED | Same ordered evidence; exactly one expiry event |

`READY` means eligible for a separate explicit execution attempt. All walkthrough
results remain `None`, approvals remain unconsumed, and both seeded balances stay
at 1,000,000 cents. Approval itself never runs a transfer.

## Reproduce the lifecycle

1. Submit a trusted agent's request through `RequestOperationHandler`, key
   `walkthrough`, transfer `acct-alice` → `acct-bob`, 10,001 cents USD. The real
   policy handler evaluates account facts from the UoW. The command commits the
   immutable operation, pending approval and original decision audit together.
2. Advance the injected clock 30 seconds. A separate trusted approver calls
   `ApproveOperationHandler` with APPROVE or REJECT. Both state updates and the
   human decision audit commit atomically. The original request, owning principal,
   fingerprint, policy and creation/deadline binding remain unchanged.
3. UoW connections close. Validate/reopen the file with
   `initialize(database, seed=False)`, construct fresh readers and an approval
   handler, and load through a fresh UoW. Verify the decision survived. Repeated
   owner/approver reads, audit listing, identical request replay and both duplicate
   decision choices leave the complete database snapshot unchanged. This models
   reopen with fresh connections/handlers, rather than a separate process restart.
4. Start another fresh database for expiry. At 299.999999 seconds, domain expiry
   is rejected. At exactly 300 seconds, `expire(now)` returns an EXPIRED approval
   and operation snapshot. Both human decision choices now raise
   `InvalidTransition`. Queries at 300, 301 and 600 seconds return the persisted
   pending states and original deadline. Reopen confirms no implicit expiry write.
5. Invoke `ExpireApprovalHandler(factory, clock).handle(ExpireApprovalCommand(id))`
   with the existing SQLite UoW factory and injected clock at the deadline. The
   command loads the current binding, calls the existing domain `expire(now)`,
   saves both states and appends `expired_event(now)` before one commit. Reopen
   preserves EXPIRED/EXPIRED and the correlated expiry event. Repeated queries
   inspect those persisted states without adding records. A grant at 299 seconds
   still expires at the original 300-second deadline.

## Atomic expiry audit

Tests compare complete persisted rows against an exact field allowlist and compare
the audit query's typed events with request/decision domain facts. Request evidence
contains event ID/type, operation ID, owning principal ID, tool, decision/reason,
policy version and UTC timestamp. Human decision evidence also contains approver
ID and canonical request fingerprint. Expiry evidence includes the fingerprint,
EXPIRED decision code, APPROVAL_EXPIRED reason/type and command observation time,
with no invented human approver. Pending expiry produces IDs 1 and 2; granted
expiry preserves its human decision and produces IDs 1, 2 and 3. Arguments, amounts,
credentials, headers, rejected raw input and exception messages have no audit fields.

`ExpireApprovalCommand` is an internal command carrying only an operation ID.
It has no endpoint, worker, scheduler or automatic query hook. A trusted internal
caller must invoke it; merely reaching the deadline does not write anything.
Before the original deadline, expiry is rejected. At or after it, pending or
granted approvals expire. Grant metadata, original policy and request bindings
remain intact. Terminal operations are never transitioned again; already expired
calls return their stored approval without a second event.

The existing `BEGIN IMMEDIATE` UoW serializes independent connections. Conditional
repository updates and the expiry audit share one transaction. If audit insertion
fails, both state updates roll back and only prior evidence remains. A later retry
can commit one expiry event. Invalid human decisions append no events. Runtime
execution, consumption and execution-policy revalidation are implemented in the
separate [execution slice](execution_harness.md), outside these expiry-only cases.
The expiry constraints introduced in schema v4 support pending/granted expiry;
the current schema is v6 and migrates supported v1–v5 databases atomically,
without replacing existing decision evidence. Queries continue to use read-only
connections; the existing audit endpoint can display expiry evidence.

## Verification map

Names below are in `tests/infrastructure/test_human_approval_walkthrough.py`.

| Requested verification | Test / evidence |
| --- | --- |
| PENDING → GRANTED → reopen | `test_pending_decision_reopen_and_correlated_sanitized_evidence`, APPROVE case |
| PENDING → REJECTED → reopen | Same test, REJECT case |
| Expiry at exactly 300 seconds | `test_exact_300_second_expiry_requires_command_and_queries_preserve_state` |
| Sanitized audit | Exact row allowlist and typed event comparisons in decision and durable-expiry tests |
| Immutable policy/request binding | `test_unauthorized_access_and_changed_request_cannot_rebind_approval`: changed request conflicts; frozen policy assignment fails; changed arguments/version/owner fail pure domain consumption checks |
| Unauthorized/duplicate decisions | Safeguard test rejects agents and same-identity self-approval; decision test rejects both duplicate choices after reopen |
| Atomic rollback on audit failure | `test_walkthrough_audit_failure_rolls_back_then_reopens_pending`, both choices; injected SQLite trigger aborts audit; both states roll back; error/log/audit exclude exception sentinel |
| Read-only queries preserve expiry state | Expiry test compares complete SQLite dumps before/after repeated reads and reopen |
| No dispatch or balance changes | Fixture checks both balances and absent results after every case; architecture and fake-port tests below check dispatch boundaries |

Complementary existing checks:

- `tests/infrastructure/test_durable_approval_expiry.py` covers pending/granted
  expiry one microsecond before/at/after the original deadline, reopen/replay,
  exact sanitized audit fields, immutable binding and grant metadata, atomic
  audit-failure rollback/retry, concurrent expiry, terminal-state rejection,
  missing operations, v3 migration and repeated read-only inspection.
- `tests/application/test_expire_approval_handler.py` covers fake-port expiry
  with no usable account/tool collaborator, mismatched snapshots and invalid IDs.
- `tests/api/test_list_audit_endpoint.py::test_existing_audit_query_exposes_expiry_without_mutation`
  checks compatibility of the existing audit query and its redacted response.

- `tests/application/test_approve_operation_handler.py::test_fake_ports_decide_without_accounts_or_tools`
  runs approval without a usable accounts/tool port.
- `tests/infrastructure/test_approval_lifecycle.py::test_persisted_binding_mismatch_fails_closed`
  rejects corrupted persisted bindings.
- `tests/application/test_approve_operation_handler.py::test_matching_unsupported_policy_rejected_by_handler`
  rejects a stale policy even when operation and approval agree.
- `tests/architecture/test_cqrs.py` enforces that dispatch belongs only to the
  execute-operation harness.

See [SQLite persistence and recovery](persistence.md) for transaction ownership
and the recovery procedure.

## Historical task 4.3 verification record

Verified on Python 3.12.14 on 2026-10-24: locked environment sync; full Pytest
suite (535 passed, including six walkthrough and nineteen durable-expiry cases);
Ruff lint and format checks;
strict Mypy over `src`; and `openspec validate --all --strict`.
Task 4.3's expiry evidence gap is closed. Only task 4.3 is marked complete; no
execution tasks, commits or pushes are part of this work.
