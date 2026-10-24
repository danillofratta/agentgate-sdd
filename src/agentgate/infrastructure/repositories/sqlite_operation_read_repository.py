import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.approval_deadline import ApprovalDeadline
from agentgate.domain.value_objects.approval_inspection import ApprovalInspection
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_inspection import OperationInspection
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.infrastructure.repositories.operation_mapper import hydrate


def _result(operation: Operation, raw: str | None) -> BalanceResult | TransferArguments | None:
    if raw is None:
        if operation.state == OperationState.SUCCEEDED:
            raise StorageUnavailable
        return None
    if operation.state != OperationState.SUCCEEDED:
        raise StorageUnavailable
    payload = json.loads(raw)
    arguments = operation.request.arguments
    if isinstance(arguments, BalanceArguments):
        if set(payload) != {"account_id", "balance_cents", "currency"}:
            raise StorageUnavailable
        result = BalanceResult(
            AccountId(payload["account_id"]), payload["balance_cents"], payload["currency"]
        )
        if result.account_id != arguments.account_id:
            raise StorageUnavailable
        return result
    if set(payload) != {"source_account_id", "destination_account_id", "amount_cents", "currency"}:
        raise StorageUnavailable
    transfer = TransferArguments(
        AccountId(payload["source_account_id"]),
        AccountId(payload["destination_account_id"]),
        Money(payload["amount_cents"], payload["currency"]),
    )
    if transfer != arguments:
        raise StorageUnavailable
    return transfer


def _approval(operation: Operation, row: sqlite3.Row | None) -> ApprovalInspection | None:
    if row is None:
        if operation.policy.decision == Decision.REQUIRE_APPROVAL:
            raise StorageUnavailable
        return None
    deadline = ApprovalDeadline(operation.created_at)
    if (
        operation.policy.decision != Decision.REQUIRE_APPROVAL
        or row["principal_id"] != operation.principal_id.value
        or row["fingerprint"] != operation.request.fingerprint.value
        or row["policy_version"] != operation.policy.version.value
        or datetime.fromisoformat(row["created_at"]) != operation.created_at
        or datetime.fromisoformat(row["expires_at"]) != deadline.expires_at
    ):
        raise StorageUnavailable
    return ApprovalInspection(
        ApprovalState(row["status"]), operation.created_at, deadline.expires_at
    )


class SqliteOperationReadRepository:
    def __init__(self, path: str) -> None:
        self._uri = Path(path).resolve().as_uri() + "?mode=ro"

    def get(self, operation_id: OperationId) -> OperationInspection | None:
        try:
            with closing(
                sqlite3.connect(self._uri, uri=True, timeout=0.05, isolation_level=None)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                # A single read transaction gives both rows one consistent snapshot.
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT * FROM operations WHERE id=?", (operation_id.value,)
                ).fetchone()
                if row is None:
                    return None
                operation = hydrate(row, stored_state=True)
                approval = connection.execute(
                    "SELECT * FROM approvals WHERE operation_id=?", (operation_id.value,)
                ).fetchone()
                return OperationInspection(
                    operation,
                    _approval(operation, approval),
                    _result(operation, row["result_json"]),
                )
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError):
            raise StorageUnavailable from None
