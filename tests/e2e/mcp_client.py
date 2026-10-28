"""Official SDK client for the fixed local AgentGate MCP endpoint; never prints credentials."""

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:8002/mcp"


@asynccontextmanager
async def connect(*, mode="legacy"):
    token = (ROOT / ".lab-secrets/mcp_token").read_text().strip()
    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + token},
        timeout=8,
        trust_env=False,
        follow_redirects=False,
    ) as http:
        async with Client(
            streamable_http_client(URL, http_client=http),
            mode=mode,
            cache=None,
            read_timeout_seconds=8,
        ) as client:
            yield client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tool", choices=["list", "request_operation", "get_operation", "execute_operation"]
    )
    parser.add_argument(
        "arguments", nargs="?", default="{}", help="JSON object matching tool schema"
    )
    args = parser.parse_args()
    async with connect() as client:
        result = (
            await client.list_tools()
            if args.tool == "list"
            else await client.call_tool(args.tool, json.loads(args.arguments))
        )
        print(result.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
