import asyncio
import json

import httpx
import httpx2
import pytest

from agentgate.application.exceptions.agent_unavailable import AgentUnavailable
from agentgate.infrastructure.gateways.openai_chat_gateway import OpenaiChatGateway
from agentgate.infrastructure.gateways.sdk_agent_mcp_gateway import SdkAgentMcpGateway
from agentgate.infrastructure.security.llm_settings import LlmSettings
from tests.agent_support import tool_call

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
