import json
import sqlite3
from typing import cast

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.operation import Operation
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.infrastructure.repositories.operation_mapper import hydrate
from agentgate.infrastructure.repositories.sqlite_approval_repository import (
    SqliteApprovalRepository,
)
from agentgate.infrastructure.repositories.sqlite_operation_read_repository import _result


class SqliteOperationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, operation_id: OperationId) -> Operation | None:
        row = self._connection.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id.value,)
        ).fetchone()
        return None if row is None else hydrate(row, stored_state=True)

    def save_approval_decision(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if operation.state not in {OperationState.READY, OperationState.REJECTED}:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        if operation.policy.decision != Decision.REQUIRE_APPROVAL:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        cursor = self._connection.execute(
            """UPDATE operations SET state=? WHERE id=? AND state='PENDING_APPROVAL'
               AND principal_id=? AND key=? AND request_json=? AND fingerprint=?
               AND decision=? AND reason=? AND policy_version=? AND created_at=?""",
            (
                operation.state.value,
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")

    def find(self, principal_id: PrincipalId, key: IdempotencyKey) -> Operation | None:
        row = cast(
            sqlite3.Row | None,
            self._connection.execute(
                "SELECT * FROM operations WHERE principal_id=? AND key=?",
                (principal_id.value, key.value),
            ).fetchone(),
        )
        if row is None:
            return None
        operation = hydrate(row, stored_state=True)
        if (
            operation.policy.decision == Decision.REQUIRE_APPROVAL
            and operation.state != OperationState.PENDING_APPROVAL
        ):
            approval = SqliteApprovalRepository(self._connection).get(operation.id)
            if approval is None or (
                approval.operation != operation
                and not (
                    operation.state in (OperationState.FAILED, OperationState.TIMED_OUT)
                    and approval.operation.transition(operation.state) == operation
                )
                and not (
                    operation.state == OperationState.SUCCEEDED
                    and operation.execution_authorization is not None
                    and approval.operation.authorize_execution(
                        operation.execution_authorization
                    ).transition(OperationState.SUCCEEDED)
                    == operation
                )
            ):
                raise StorageUnavailable
        return operation

    def save_approval_expiry(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if (
            operation.state != OperationState.EXPIRED
            or operation.policy.decision != Decision.REQUIRE_APPROVAL
        ):
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")
        cursor = self._connection.execute(
            """UPDATE operations SET state='EXPIRED'
               WHERE id=? AND state IN ('PENDING_APPROVAL','READY') AND result_json IS NULL
               AND principal_id=? AND key=? AND request_json=? AND fingerprint=?
               AND decision=? AND reason=? AND policy_version=? AND created_at=?""",
            (
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_APPROVAL_TRANSITION")

    def get_result(self, operation_id: OperationId) -> BalanceResult | TransferArguments | None:
        row = self._connection.execute(
            "SELECT * FROM operations WHERE id=?", (operation_id.value,)
        ).fetchone()
        if row is None:
            return None
        try:
            return _result(hydrate(row, stored_state=True), row["result_json"])
        except (ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None

    def save_execution(
        self, operation: Operation, result: BalanceResult | TransferArguments
    ) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        arguments = operation.request.arguments
        if (
            operation.state != OperationState.SUCCEEDED
            or operation.execution_authorization is None
            or not (
                (
                    isinstance(arguments, BalanceArguments)
                    and type(result) is BalanceResult
                    and result.account_id == arguments.account_id
                )
                or (type(result) is TransferArguments and result == arguments)
            )
        ):
            raise InvalidTransition("INVALID_EXECUTION_RESULT")
        result_json = json.dumps(
            {
                "account_id": result.account_id.value,
                "balance_cents": result.balance_cents,
                "currency": result.currency,
            }
            if isinstance(result, BalanceResult)
            else {
                "source_account_id": result.source_account_id.value,
                "destination_account_id": result.destination_account_id.value,
                "amount_cents": result.amount.cents,
                "currency": result.amount.currency,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        cursor = self._connection.execute(
            """UPDATE operations SET state='SUCCEEDED', result_json=?, authorization_json=?
               WHERE id=? AND state='READY' AND result_json IS NULL
               AND principal_id=? AND key=? AND request_json=? AND fingerprint=?
               AND decision=? AND reason=? AND policy_version=? AND created_at=?""",
            (
                result_json,
                json.dumps(
                    {
                        "decision": operation.execution_authorization.decision.value,
                        "reason": operation.execution_authorization.reason.value,
                        "version": operation.execution_authorization.version.value,
                    },
                    sort_keys=True,
                ),
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_OPERATION_TRANSITION")

    def save_failure(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        if operation.state not in (OperationState.FAILED, OperationState.TIMED_OUT):
            raise InvalidTransition("INVALID_OPERATION_TRANSITION")
        stored = self.get(operation.id)
        if stored is None or stored.transition(operation.state) != operation:
            raise InvalidTransition("INVALID_OPERATION_TRANSITION")
        cursor = self._connection.execute(
            """UPDATE operations SET state=? WHERE id=? AND state='READY'
               AND result_json IS NULL AND authorization_json IS NULL""",
            (operation.state.value, operation.id.value),
        )
        if cursor.rowcount != 1:
            raise InvalidTransition("INVALID_OPERATION_TRANSITION")

    def add(self, operation: Operation) -> None:
        if not self._connection.in_transaction:
            raise StorageUnavailable
        self._connection.execute(
            """INSERT INTO operations(id, principal_id, key, request_json, fingerprint,
               decision, reason, policy_version, created_at, state) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                operation.id.value,
                operation.principal_id.value,
                operation.key.value,
                operation.request.canonical_json(),
                operation.request.fingerprint.value,
                operation.policy.decision.value,
                operation.policy.reason.value,
                operation.policy.version.value,
                operation.created_at.isoformat(),
                operation.state.value,
            ),
        )
