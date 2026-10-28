import copy
import re
from typing import Any

from agentgate.domain.enums.reason import Reason
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.transfer_arguments import TransferArguments

ALLOWED = frozenset({"request_operation", "get_operation", "execute_operation"})


def definitions(discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(discovered) != 3 or {t.get("name") for t in discovered} != ALLOWED:
        raise ValueError("MCP_TOOLS_INVALID")
    result = []
    for tool in discovered:
        name = tool["name"]
        schema = copy.deepcopy(tool["parameters"])
        expected = (
            {"tool_name", "arguments", "idempotency_key"}
            if name == "request_operation"
            else {"operation_id"}
        )
        if (
            schema.get("additionalProperties") is not False
            or set(schema.get("properties", {})) != expected
        ):
            raise ValueError("MCP_TOOLS_INVALID")
        if name == "request_operation":
            account = {"type": "string", "pattern": "^acct-[a-z0-9]{1,32}$"}
            for alias, properties in (
                ("request_balance", {"account_id": account}),
                (
                    "request_transfer",
                    {
                        "source_account_id": account,
                        "destination_account_id": account,
                        "amount_cents": {"type": "integer", "minimum": 1, "maximum": 2**63 - 1},
                        "currency": {"type": "string", "enum": ["USD"]},
                    },
                ),
            ):
                result.append(
                    {
                        "type": "function",
                        "function": {
                            "name": alias,
                            "description": (
                                "Propose a balance read. Never executes."
                                if alias == "request_balance"
                                else "Propose a simulated transfer in integer cents. "
                                "Never executes; "
                                "requires explicit UI execution and independent approval if needed."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": copy.deepcopy(properties),
                                "required": list(properties),
                                "additionalProperties": False,
                            },
                        },
                    }
                )
            continue
        # Names and descriptions are trusted locally; discovered descriptions are untrusted.
        description = {
            "get_operation": "Inspect an operation already returned in this conversation.",
            "execute_operation": (
                "Execute a balance read, or a transfer after the explicit UI execute action "
                "for that ID. Cannot approve."
            ),
        }[name]
        result.append(
            {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": schema},
            }
        )
    return result


def llm_arguments(name: str, raw: Any) -> tuple[str, dict[str, Any]]:
    """Translate flat model tools into validated MCP payloads without coercion."""
    proposals = {"request_balance": "get_balance", "request_transfer": "simulate_transfer"}
    if name in proposals:
        return "request_operation", arguments(
            "request_operation", {"tool_name": proposals[name], "arguments": raw}
        )
    if name not in {"get_operation", "execute_operation"}:
        raise ValueError("INVALID_TOOL_CALL")
    return name, arguments(name, raw)


def arguments(name: str, raw: Any) -> dict[str, Any]:
    if name not in ALLOWED or not isinstance(raw, dict):
        raise ValueError("INVALID_TOOL_CALL")
    if name != "request_operation":
        if set(raw) != {"operation_id"}:
            raise ValueError("INVALID_TOOL_CALL")
        return {"operation_id": OperationId(raw["operation_id"]).value}
    if set(raw) != {"tool_name", "arguments"} or not isinstance(raw["arguments"], dict):
        raise ValueError("INVALID_TOOL_CALL")
    tool, values = raw["tool_name"], raw["arguments"]
    if tool == "get_balance" and set(values) == {"account_id"}:
        BalanceArguments(AccountId(values["account_id"]))
    elif tool == "simulate_transfer" and set(values) == {
        "source_account_id",
        "destination_account_id",
        "amount_cents",
        "currency",
    }:
        TransferArguments(
            AccountId(values["source_account_id"]),
            AccountId(values["destination_account_id"]),
            Money(values["amount_cents"], values["currency"]),
        )
    else:
        raise ValueError("INVALID_TOOL_CALL")
    return {"tool_name": tool, "arguments": dict(values)}


def safe_result(raw: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Drop all unknown fields/text, including untrusted errors and tool instructions."""
    status = raw.get("http_status")
    if type(status) is not int or not 200 <= status <= 599:
        raise ValueError("MCP_RESULT_INVALID")
    if status not in {200, 201}:
        return {"http_status": status, "error": "OPERATION_UNAVAILABLE"}
    op_id = OperationId(raw["id"]).value
    state = raw.get("state")
    decision = raw.get("decision")
    if state not in {
        "READY",
        "PENDING_APPROVAL",
        "DENIED",
        "REJECTED",
        "EXPIRED",
        "SUCCEEDED",
        "FAILED",
        "TIMED_OUT",
        "EXECUTING",
    } or decision not in {"ALLOW", "DENY", "REQUIRE_APPROVAL"}:
        raise ValueError("MCP_RESULT_INVALID")
    validated = arguments(
        "request_operation",
        {
            "tool_name": raw.get("tool"),
            "arguments": raw.get("arguments", (previous or {}).get("arguments")),
        },
    )
    clean: dict[str, Any] = {
        "http_status": status,
        "id": op_id,
        "state": state,
        "decision": decision,
        "simulation": True,
        "tool": validated["tool_name"],
        "arguments": validated["arguments"],
    }
    for key in ("reason", "effective_reason"):
        if raw.get(key) in {r.value for r in Reason}:
            clean[key] = raw[key]
    if raw.get("effective_decision") in {"ALLOW", "DENY", "REQUIRE_APPROVAL"}:
        clean["effective_decision"] = raw["effective_decision"]
    if raw.get("policy_version") == "v1":
        clean["policy_version"] = "v1"
    result = raw.get("result")
    if isinstance(result, dict) and state == "SUCCEEDED":
        clean["result"] = {
            key: value
            for key, value in result.items()
            if key
            in {
                "balance_cents",
                "amount_cents",
                "source_balance_cents",
                "destination_balance_cents",
                "account_id",
                "source_account_id",
                "destination_account_id",
                "currency",
            }
            and (
                type(value) is int
                and 0 <= value <= 2**63 - 1
                or isinstance(value, str)
                and re.fullmatch(r"acct-[a-z0-9]{1,32}|USD", value)
            )
        }
    return clean
