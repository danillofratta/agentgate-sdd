import json
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agentgate.application.ports.mcp_api_gateway import McpApiGateway
from agentgate.features.mcp_ingress.models import OperationReference, Submission


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ready", "simulation": True})


health_route = Route("/health", health)


def build_server(gateway: McpApiGateway) -> Server[None]:
    async def list_tools(
        context: ServerRequestContext[None],
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="request_operation",
                    description="Submit for policy evaluation; never executes.",
                    input_schema=Submission.model_json_schema(),
                    annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False),
                ),
                Tool(
                    name="get_operation",
                    description="Inspect the owning agent's persisted operation.",
                    input_schema=OperationReference.model_json_schema(),
                    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
                ),
                Tool(
                    name="execute_operation",
                    description="Explicit execution or durable replay by ID.",
                    input_schema=OperationReference.model_json_schema(),
                    annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False),
                ),
            ]
        )

    async def call_tool(
        context: ServerRequestContext[None],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        status, body = 422, {"error": "INVALID_INPUT"}
        try:
            if params.name == "request_operation":
                submission = Submission.model_validate(params.arguments)
                status, body = await gateway.submit(
                    {"tool": submission.tool_name, "arguments": submission.arguments.model_dump()},
                    submission.idempotency_key,
                )
            elif params.name in {"get_operation", "execute_operation"}:
                reference = OperationReference.model_validate(params.arguments)
                if params.name == "get_operation":
                    status, body = await gateway.inspect(reference.operation_id)
                else:
                    status, body = await gateway.run_operation(reference.operation_id)
        except ValidationError:
            pass  # Never return/log Pydantic errors containing rejected raw arguments.
        except Exception:
            status, body = 503, {"error": "API_UNAVAILABLE"}
        result: dict[str, Any] = {"http_status": status, **body}
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))],
            structured_content=result,
            is_error=status >= 400,
        )

    return Server(
        "AgentGate simulation", version="1.0", on_list_tools=list_tools, on_call_tool=call_tool
    )
