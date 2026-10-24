import json
import sqlite3
from datetime import datetime

from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


def hydrate(row: sqlite3.Row) -> Operation:
    payload = json.loads(row["request_json"])
    args = payload["arguments"]
    request = OperationRequest(
        BalanceArguments(AccountId(args["account_id"]))
        if payload["tool"] == "get_balance"
        else TransferArguments(
            AccountId(args["source_account_id"]),
            AccountId(args["destination_account_id"]),
            Money(args["amount_cents"], args["currency"]),
        )
    )
    return Operation(
        OperationId(row["id"]),
        PrincipalId(row["principal_id"]),
        IdempotencyKey(row["key"]),
        request,
        PolicyDecision(
            Decision(row["decision"]), Reason(row["reason"]), PolicyVersion(row["policy_version"])
        ),
        datetime.fromisoformat(row["created_at"]),
    )
