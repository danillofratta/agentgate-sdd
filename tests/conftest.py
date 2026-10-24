import socket
import subprocess
import threading
from datetime import UTC, datetime

import pytest

from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.domain.value_objects.tool import Tool
from agentgate.infrastructure.persistence.database import initialize
from agentgate.infrastructure.security.settings import Settings

AGENT_TOKEN = "test-A6b9C2d5E8f1G4h7J0k3L6m9N2p5Q8r1"
APPROVER_TOKEN = "test-U8v1W4x7Y0z3A6b9C2d5E8f1G4h7J0k3"


@pytest.fixture(autouse=True)
def offline(monkeypatch):

    def forbidden(*args, **kwargs):
        raise AssertionError("External network and subprocesses are forbidden in tests")

    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    internal = threading.local()

    def guarded_connect(connection, address):
        if getattr(internal, "socketpair", False):
            return original_connect(connection, address)
        return forbidden()

    def local_socketpair(*args, **kwargs):
        internal.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            internal.socketpair = False

    monkeypatch.setattr(socket, "socketpair", local_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def principal():
    return Principal(
        PrincipalId("principal-agent"),
        Role.AGENT,
        frozenset(Tool),
        frozenset({AccountId("acct-alice")}),
    )


@pytest.fixture
def database(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    initialize(path, seed=True)
    return path


@pytest.fixture
def settings(database):
    return Settings(AGENT_TOKEN, APPROVER_TOKEN, database)


class FakeClock:
    def __init__(self):
        self.value = datetime(2026, 10, 23, 12, tzinfo=UTC)

    def now(self):
        return self.value


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sleeper():
    delays = []
    return delays.append
