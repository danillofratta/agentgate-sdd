import json
from datetime import datetime
from typing import Any

from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.tool import Tool
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


def hydrate(row: Any, *, stored_state: bool = False) -> Operation:
    try:
        return _hydrate(row, stored_state=stored_state)
    except (ValueError, TypeError, KeyError, IndexError):
        raise StorageUnavailable from None


def _hydrate(row: Any, *, stored_state: bool) -> Operation:
    payload = json.loads(row["request_json"])
    args = payload["arguments"]
    tool = Tool(payload["tool"])
    request = OperationRequest(
        BalanceArguments(AccountId(args["account_id"]))
        if tool == Tool.GET_BALANCE
        else TransferArguments(
            AccountId(args["source_account_id"]),
            AccountId(args["destination_account_id"]),
            Money(args["amount_cents"], args["currency"]),
        )
    )
    if request.canonical_json() != row["request_json"]:
        raise StorageUnavailable
    if request.fingerprint.value != row["fingerprint"]:
        raise StorageUnavailable
    operation = Operation(
        OperationId(row["id"]),
        PrincipalId(row["principal_id"]),
        IdempotencyKey(row["key"]),
        request,
        PolicyDecision(
            Decision(row["decision"]), Reason(row["reason"]), PolicyVersion(row["policy_version"])
        ),
        datetime.fromisoformat(row["created_at"]),
    )
    state = OperationState(row["state"])
    authorization = row["authorization_json"] if "authorization_json" in row.keys() else None
    if stored_state and state != operation.state:
        # Hydrate through the domain lifecycle without replaying commands or policy.
        if operation.state == OperationState.PENDING_APPROVAL and state in {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.TIMED_OUT,
            OperationState.DENIED,
        }:
            operation = operation.transition(OperationState.READY)
        if authorization is not None:
            payload = json.loads(authorization)
            if (
                set(payload) != {"decision", "reason", "version"}
                or state != OperationState.SUCCEEDED
            ):
                raise StorageUnavailable
            operation = operation.authorize_execution(
                PolicyDecision(
                    Decision(payload["decision"]),
                    Reason(payload["reason"]),
                    PolicyVersion(payload["version"]),
                )
            )
        operation = operation.transition(state)
    elif operation.state != state:
        raise StorageUnavailable
    return operation
