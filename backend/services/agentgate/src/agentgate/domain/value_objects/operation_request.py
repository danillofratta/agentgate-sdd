import hashlib
import json
from dataclasses import dataclass

from agentgate.domain.enums.tool import Tool
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.request_fingerprint import RequestFingerprint
from agentgate.domain.value_objects.transfer_arguments import TransferArguments


@dataclass(frozen=True)
class OperationRequest:
    arguments: BalanceArguments | TransferArguments

    def __post_init__(self) -> None:
        if not isinstance(self.arguments, (BalanceArguments, TransferArguments)):
            raise InvariantViolation("INVALID_ARGUMENTS")

    @property
    def tool(self) -> Tool:
        return (
            Tool.GET_BALANCE
            if isinstance(self.arguments, BalanceArguments)
            else Tool.SIMULATE_TRANSFER
        )

    @property
    def source(self) -> AccountId:
        args = self.arguments
        return args.account_id if isinstance(args, BalanceArguments) else args.source_account_id

    def canonical_json(self) -> str:
        args = self.arguments
        arguments: dict[str, str | int]
        if isinstance(args, BalanceArguments):
            arguments = {"account_id": args.account_id.value}
        else:
            arguments = {
                "source_account_id": args.source_account_id.value,
                "destination_account_id": args.destination_account_id.value,
                "amount_cents": args.amount.cents,
                "currency": args.amount.currency,
            }
        return json.dumps(
            {"tool": self.tool.value, "arguments": arguments}, sort_keys=True, separators=(",", ":")
        )

    @property
    def fingerprint(self) -> RequestFingerprint:
        return RequestFingerprint(hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest())
