FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM python:3.12-slim AS runtime
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --python 3.12 \
    && groupadd --gid 10001 agentgate \
    && useradd --uid 10001 --gid 10001 --create-home agentgate
USER agentgate
CMD ["/app/.venv/bin/uvicorn", "agentgate.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM runtime AS verification
USER root
COPY tests ./tests
COPY integration_tests ./integration_tests
RUN uv sync --locked --python 3.12
USER agentgate
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["/app/.venv/bin/pytest", "integration_tests", "-q", "-p", "no:cacheprovider"]

FROM runtime AS final
