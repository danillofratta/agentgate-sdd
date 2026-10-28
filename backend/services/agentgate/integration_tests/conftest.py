"""Opt-in real local PostgreSQL only; never touches the persistent demo database."""

import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest

from agentgate.dependencies import build_components
from agentgate.infrastructure.persistence.postgres_database import initialize
from agentgate.infrastructure.security.settings import Settings
from agentgate.main import create_app


@pytest.fixture(autouse=True)
def local_services_only(monkeypatch):
    host = os.environ.get("AGENTGATE_TEST_POSTGRES")
    if host != "postgres-test":
        pytest.skip("Run with compose.test.yaml against the disposable postgres-test service")
    original = psycopg.connect

    def guarded(database, *args, **kwargs):
        from psycopg.conninfo import conninfo_to_dict

        fields = conninfo_to_dict(database)
        assert fields["host"] == host and fields["dbname"] == "agentgate_test"
        return original(database, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Subprocess and external services forbidden")

    monkeypatch.setattr(psycopg, "connect", guarded)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def pg_database():
    password = Path(os.environ["AGENTGATE_TEST_PASSWORD_FILE"]).read_text().strip()
    database = (
        "postgresql://agentgate:" + quote(password, safe="") + "@postgres-test/agentgate_test"
    )
    initialize(database, seed=True)
    with psycopg.connect(database) as connection:
        connection.execute(
            "TRUNCATE audit_events, approvals, operations, accounts RESTART IDENTITY"
        )
    initialize(database, seed=True)
    yield database


@pytest.fixture
def pg_settings(pg_database):
    return Settings(secrets.token_urlsafe(48), secrets.token_urlsafe(48), pg_database)


@pytest.fixture
def api(pg_settings):
    from fastapi.testclient import TestClient

    with TestClient(
        create_app(build_components(pg_settings), local=True), base_url="http://127.0.0.1:8000"
    ) as client:
        yield client


@pytest.fixture
def auth(pg_settings):
    return {"Authorization": "Bearer " + pg_settings.agent_token}


@pytest.fixture
def human(pg_settings):
    return {"Authorization": "Bearer " + pg_settings.approver_token}
