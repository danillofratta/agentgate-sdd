# AgentGate backend

One Python project, three processes: `agentgate.main:create_app`,
`agentgate.lab:create_app` (Lab BFF), and `agentgate.mcp:create_app`.
Run from this directory:

```sh
uv sync --locked --python 3.12
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy --strict src
```

Repository-wide Compose, secrets, documentation and OpenSpec live three levels up.
See [repository README](../../../README.md) and [architecture](../../../docs/architecture.md).
