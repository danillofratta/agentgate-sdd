"""TEST ONLY factory: deterministic fake LLM, actual MCP/API/PostgreSQL. Never in default image."""

import json

from agentgate.features.chat_turn.handler import ChatTurnHandler
from agentgate.infrastructure.gateways.sdk_agent_mcp_gateway import SdkAgentMcpGateway
from agentgate.infrastructure.runtime.chat_sessions import ChatSessions
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.security.settings import secret
from agentgate.lab import create_app as lab_app


def call(name, arguments):
    return {
        "content": None,
        "tool_calls": [
            {
                "id": "verification-call",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


class VerificationLlm:
    async def verify_tools(self):
        pass

    async def complete(self, messages, tools, required=None):
        last = messages[-1]
        snapshots = []
        for message in messages:
            if message.get("content", "") and message["content"].startswith(
                "Untrusted MCP snapshots"
            ):
                snapshots = json.loads(message["content"].split(": ", 1)[1])
        if required:
            return call(required, {"operation_id": snapshots[-1]["id"]})
        if last["role"] == "tool":
            result = json.loads(last["content"])
            if result.get("tool") == "get_balance" and result.get("state") == "READY":
                return call("execute_operation", {"operation_id": result["id"]})
            return {
                "content": "Verification model: inspect the authoritative operation card.",
                "tool_calls": [],
            }
        user = next(
            m["content"]
            for m in reversed(messages)
            if m["role"] == "user" and not m["content"].startswith("Untrusted MCP snapshots")
        )
        if "last operation" in user.lower() and snapshots:
            return call("get_operation", {"operation_id": snapshots[-1]["id"]})
        if "balance" in user.lower():
            return call(
                "request_balance",
                {"account_id": "acct-alice"},
            )
        amount = 100001 if "$1,000.01" in user else 10001 if "$100.01" in user else 100
        return call(
            "request_transfer",
            {
                "source_account_id": "acct-alice",
                "destination_account_id": "acct-bob",
                "amount_cents": amount,
                "currency": "USD",
            },
        )


def create_app():
    handler = ChatTurnHandler(
        VerificationLlm(),
        SdkAgentMcpGateway(secret("AGENTGATE_MCP_TOKEN")),
        ChatSessions(),
        UuidOperationIdGenerator(),
        6,
        12,
        30,
    )
    return lab_app(chat_handler=handler)
