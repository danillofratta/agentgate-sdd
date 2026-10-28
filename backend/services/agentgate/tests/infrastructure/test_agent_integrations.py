import asyncio
import json

import httpx
import httpx2
import pytest

from agentgate.application.exceptions.agent_unavailable import AgentUnavailable
from agentgate.features.chat_turn.command import ChatTurnCommand
from agentgate.infrastructure.gateways.openai_chat_gateway import OpenaiChatGateway
from agentgate.infrastructure.gateways.sdk_agent_mcp_gateway import SdkAgentMcpGateway
from agentgate.infrastructure.security.llm_settings import LlmSettings
from tests.agent_support import tool_call
from tests.application.test_agent_safety import FakeMcp, handler

KEY = "test-only-provider-secret-never-valid"


def settings(provider="openai", **kwargs):
    base = "https://api.openai.com/v1" if provider == "openai" else "https://api.groq.com/openai/v1"
    return LlmSettings(provider, base, "test-tool-model", KEY, **kwargs)


@pytest.fixture
def provider_http(monkeypatch):
    original = httpx.AsyncClient

    def install(callback):
        def factory(*args, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
            kwargs["transport"] = httpx.MockTransport(callback)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    return install


@pytest.mark.parametrize("provider", ["openai", "groq"])
def test_actual_provider_wire_contract_and_capability_probe(provider_http, provider, caplog):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer " + KEY
        body = tool_call("capability_probe", {})
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "tool_calls", "message": body}]}
        )

    provider_http(respond)

    async def run():
        gateway = OpenaiChatGateway(settings(provider))
        await gateway.verify_tools()
        await gateway.verify_tools()

    asyncio.run(run())
    assert len(seen) == 1
    assert seen[0]["tool_choice"]["function"]["name"] == "capability_probe"
    assert seen[0]["parallel_tool_calls"] is False
    assert seen[0]["max_completion_tokens"] == 512
    assert KEY not in caplog.text


@pytest.mark.parametrize(
    "message,name,arguments,business_tool",
    [
        (
            "What is Alice's balance?",
            "request_balance",
            {"account_id": "acct-alice"},
            "get_balance",
        ),
        (
            "Transfer $1 from Alice to Bob.",
            "request_transfer",
            {
                "source_account_id": "acct-alice",
                "destination_account_id": "acct-bob",
                "amount_cents": 100,
                "currency": "USD",
            },
            "simulate_transfer",
        ),
    ],
)
def test_groq_natural_language_flat_tools_on_wire(
    provider_http, message, name, arguments, business_tool
):
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        assert request.url == "https://api.groq.com/openai/v1/chat/completions"
        assert "disable_tool_validation" not in payload
        seen.append(payload)
        if len(seen) == 1:
            response = tool_call("capability_probe", {})
        elif len(seen) == 2:
            tools = {t["function"]["name"]: t["function"]["parameters"] for t in payload["tools"]}
            assert "request_operation" not in tools
            assert set(tools[name]["properties"]) == set(arguments)
            assert all(p["type"] != "object" for p in tools[name]["properties"].values())
            assert payload["messages"][-1]["content"] == message
            response = tool_call(name, arguments)
        else:
            assert payload["messages"][-2]["tool_calls"][0]["function"]["name"] == name
            response = {"content": "Inspect the authoritative card.", "tool_calls": []}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls" if len(seen) < 3 else "stop",
                        "message": response,
                    }
                ]
            },
        )

    provider_http(respond)

    async def run():
        mcp = FakeMcp()
        mcp.body.update(tool=business_tool, arguments=arguments)
        result = await handler(OpenaiChatGateway(settings("groq")), mcp).handle(
            ChatTurnCommand("one", message)
        )
        assert result.error is None
        assert len(mcp.calls) == 1
        assert mcp.calls[0][0] == "request_operation"
        assert mcp.calls[0][1]["tool_name"] == business_tool
        assert mcp.calls[0][1]["arguments"] == arguments
        assert isinstance(mcp.calls[0][1]["arguments"], dict)

    asyncio.run(run())
    assert len(seen) == 3


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="secret-sentinel"),
        httpx.Response(429, text="secret-sentinel"),
        httpx.Response(500, text="secret-sentinel"),
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": "truncated"}}]},
        ),
        httpx.Response(200, content=b"malformed secret-sentinel"),
    ],
)
def test_provider_failures_are_sanitized_without_retries(provider_http, response, caplog):
    count = []

    def respond(request):
        count.append(request)
        return response

    provider_http(respond)
    with pytest.raises(AgentUnavailable) as error:
        asyncio.run(OpenaiChatGateway(settings()).complete([], []))
    assert str(error.value) == "" and len(count) == 1
    assert "secret-sentinel" not in caplog.text


def test_provider_timeout_and_secret_redaction(provider_http, caplog):
    def timeout(request):
        raise httpx.ReadTimeout("secret-sentinel", request=request)

    provider_http(timeout)
    with pytest.raises(AgentUnavailable):
        asyncio.run(OpenaiChatGateway(settings()).verify_tools())
    provider_http(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": KEY + " mcp-secret"}}]
            },
        )
    )
    result = asyncio.run(OpenaiChatGateway(settings(), ("mcp-secret",)).complete([], []))
    assert result["content"] == "[REDACTED] [REDACTED]"
    assert KEY not in caplog.text and "secret-sentinel" not in caplog.text


def test_provider_without_tool_support_fails_closed(provider_http):
    provider_http(
        lambda _: httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "No tools"}}]}
        )
    )
    with pytest.raises(AgentUnavailable):
        asyncio.run(OpenaiChatGateway(settings()).verify_tools())


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeout": float("nan")},
        {"timeout": 0},
        {"max_calls": 0},
        {"max_calls": 13},
        {"max_history": 25},
        {"max_tokens": 10000},
    ],
)
def test_bounded_provider_configuration(overrides):
    with pytest.raises(ValueError):
        settings(**overrides)


def test_configuration_and_repr_do_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("AGENTGATE_LLM_API_KEY", KEY)
    monkeypatch.delenv("AGENTGATE_LLM_API_KEY_FILE", raising=False)
    monkeypatch.setenv("AGENTGATE_LLM_MODEL", "test-tool-model")
    assert KEY not in repr(LlmSettings.from_environment())
    for name, value in (
        ("AGENTGATE_LLM_BASE_URL", "https://evil.example"),
        ("AGENTGATE_LLM_MODEL", "bad\nmodel"),
    ):
        with monkeypatch.context() as patch:
            patch.setenv(name, value)
            with pytest.raises(ValueError) as error:
                LlmSettings.from_environment()
            assert KEY not in str(error.value)


def test_official_mcp_client_disconnection_is_sanitized(monkeypatch, caplog):
    original = httpx2.AsyncClient

    def disconnected(request):
        raise httpx2.ConnectError("secret-sentinel", request=request)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx2.MockTransport(disconnected)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", factory)
    gateway = SdkAgentMcpGateway("mcp-secret", "http://127.0.0.1:8002/mcp")
    with pytest.raises(AgentUnavailable) as error:
        asyncio.run(gateway.discover())
    assert str(error.value) == ""
    assert "mcp-secret" not in caplog.text
    assert "secret-sentinel" not in caplog.text
