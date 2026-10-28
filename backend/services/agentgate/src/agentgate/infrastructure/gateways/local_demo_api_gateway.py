from typing import Any

import httpx


class LocalDemoApiGateway:
    """Fixed internal API destination; credentials never leave this server adapter."""

    def __init__(self, agent_token: str, approver_token: str) -> None:
        self._agent = agent_token
        self._approver = approver_token

    def _request(
        self,
        method: str,
        path: str,
        *,
        human: bool = False,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> tuple[int, Any]:
        headers = {"Authorization": "Bearer " + (self._approver if human else self._agent)}
        if key is not None:
            headers["Idempotency-Key"] = key
        try:
            with httpx.Client(
                base_url="http://api:8000", timeout=4, trust_env=False, follow_redirects=False
            ) as client:
                response = client.request(method, path, json=payload, headers=headers)
                if response.status_code not in {200, 201, 401, 403, 404, 409, 413, 422, 503}:
                    return 503, {"error": "API_UNAVAILABLE"}
                return response.status_code, response.json()
        except (httpx.HTTPError, ValueError):
            return 503, {"error": "API_UNAVAILABLE"}

    def submit(self, payload: dict[str, Any], key: str) -> tuple[int, Any]:
        return self._request("POST", "/operations", payload=payload, key=key)

    def inspect(self, operation_id: str) -> tuple[int, Any]:
        return self._request("GET", "/operations/" + operation_id)

    def decide(self, operation_id: str, payload: dict[str, Any]) -> tuple[int, Any]:
        return self._request(
            "POST", "/operations/" + operation_id + "/approval", payload=payload, human=True
        )

    def run_operation(self, operation_id: str) -> tuple[int, Any]:
        return self._request("POST", "/operations/" + operation_id + "/execute")

    def accounts(self) -> tuple[int, Any]:
        return self._request("GET", "/accounts", human=True)

    def audit(self, after: int) -> tuple[int, Any]:
        return self._request("GET", f"/audit?after={after}&limit=100", human=True)
