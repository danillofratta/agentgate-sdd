import json
from datetime import datetime
from typing import Any

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
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


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


def _approval(operation: Operation, row: Any | None) -> ApprovalInspection | None:
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
