"""Opt-in real-provider smoke. No key/model -> SKIP; never part of mandatory offline CI."""

import argparse
import asyncio
import os
from pathlib import Path

from agentgate.features.chat_turn.command import ChatTurnCommand
from agentgate.features.chat_turn.handler import ChatTurnHandler
from agentgate.infrastructure.gateways.openai_chat_gateway import OpenaiChatGateway
from agentgate.infrastructure.gateways.sdk_agent_mcp_gateway import SdkAgentMcpGateway
from agentgate.infrastructure.runtime.chat_sessions import ChatSessions
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.security.llm_settings import LlmSettings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real-provider",
        action="store_true",
        help="Opt in to one paid, synthetic balance-query conversation",
    )
    args = parser.parse_args()
    if not args.real_provider:
        print("SKIP: pass --real-provider to opt in to a billable LLM smoke test")
        return
    root = Path(__file__).resolve().parents[1]
    key_file = root / ".lab-secrets/llm_api_key"
    if not os.environ.get("AGENTGATE_LLM_API_KEY") and key_file.exists():
        os.environ.setdefault("AGENTGATE_LLM_API_KEY_FILE", str(key_file))
    configured = LlmSettings.from_environment()
    if configured is None:
        print("SKIP: no real provider credential; interoperability remains unverified")
        return
    token = (root / ".lab-secrets/mcp_token").read_text().strip()
    handler = ChatTurnHandler(
        OpenaiChatGateway(configured, (token,)),
        SdkAgentMcpGateway(token, "http://127.0.0.1:8002/mcp"),
        ChatSessions(),
        UuidOperationIdGenerator(),
        configured.max_calls,
        configured.max_history,
        120,
    )
    result = await handler.handle(ChatTurnCommand("smoke", "What is Alice's balance?"))
    assert result.error is None, "Real provider or MCP smoke failed (details suppressed)"
    assert any(
        op.get("state") == "SUCCEEDED"
        and op.get("tool") == "get_balance"
        and "balance_cents" in op.get("result", {})
        for op in result.operations
    ), "No authoritative MCP balance result"
    print(
        f"PASS: real {configured.provider} / {configured.model}; "
        "tool capability probe and actual MCP balance execution"
    )
    for event in result.events:
        if event.get("tool"):
            body = event.get("result", {})
            print(
                f"MCP {event['tool']}: HTTP {body.get('http_status')} · "
                f"{body.get('id')} · {body.get('state')}"
            )


if __name__ == "__main__":
    asyncio.run(main())
