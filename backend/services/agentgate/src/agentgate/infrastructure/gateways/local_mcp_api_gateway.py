from typing import Any

import httpx


class LocalMcpApiGateway:
    """Agent-only HTTP adapter. No approval credential, configurable destination or SQL."""

    def __init__(self, client: httpx.AsyncClient, agent_token: str) -> None:
        self._client = client
        self._agent_token = agent_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Authorization": "Bearer " + self._agent_token}
        if key is not None:
            headers["Idempotency-Key"] = key
        try:
            # Execute must have a truly empty body, not JSON null or {}.
            options: dict[str, Any] = {} if payload is None else {"json": payload}
            response = await self._client.request(method, path, headers=headers, **options)
            if response.status_code in {200, 201}:
                body = response.json()
                if isinstance(body, dict):
                    return response.status_code, body
            errors = {
                401: "UNAUTHENTICATED",
                403: "FORBIDDEN",
                404: "NOT_FOUND",
                409: "CONFLICT",
                413: "BODY_TOO_LARGE",
                422: "INVALID_INPUT",
            }
            return response.status_code, {
                "error": errors.get(response.status_code, "API_UNAVAILABLE")
            }
        except (httpx.HTTPError, ValueError):
            return 503, {"error": "API_UNAVAILABLE"}

    async def submit(self, payload: dict[str, Any], key: str) -> tuple[int, dict[str, Any]]:
        return await self._request("POST", "/operations", payload=payload, key=key)

    async def inspect(self, operation_id: str) -> tuple[int, dict[str, Any]]:
        return await self._request("GET", "/operations/" + operation_id)

    async def run_operation(self, operation_id: str) -> tuple[int, dict[str, Any]]:
        return await self._request("POST", "/operations/" + operation_id + "/execute")
