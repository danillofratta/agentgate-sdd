import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from agentgate.dependencies import build_components
from agentgate.features.request_operation.models import OperationBody
from agentgate.main import create_app
from tests.api.test_request_endpoint import headers, payload
from tests.conftest import AGENT_TOKEN


@pytest.fixture
def client(settings):
    with TestClient(create_app(build_components(settings))) as instance:
        yield instance


def snapshot(database):
    with sqlite3.connect(database) as connection:
        return tuple(
            connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("accounts", "operations", "approvals", "audit_events")
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_account_id", "acct-alice\n"),
        ("source_account_id", "acct-" + "a" * 33),
        ("source_account_id", True),
        ("destination_account_id", "acct-a'; DROP TABLE accounts;--"),
        ("destination_account_id", "../acct-bob"),
        ("destination_account_id", "acct-alice"),
        ("amount_cents", 1.0),
        ("amount_cents", None),
        ("currency", "usd"),
        ("currency", True),
        ("currency", None),
        ("currency", "USD\n"),
        ("override", {"role": "APPROVER", "decision": "ALLOW"}),
    ],
)
def test_schema_and_http_reject_invalid_inputs_before_persistence(client, database, field, value):
    body = payload()
    body["arguments"][field] = value
    with pytest.raises(ValidationError):
        TypeAdapter(OperationBody).validate_python(body)
    before = snapshot(database)
    response = client.post("/operations", headers=headers(), json=body)
    assert response.status_code == 422
    assert response.json() == {"error": "INVALID_INPUT"}
    assert snapshot(database) == before


@pytest.mark.parametrize("key", ["key\n", "key ", "a/b", "a.b", "a" * 65])
def test_header_keys_are_fully_anchored(client, database, key):
    before = snapshot(database)
    assert client.post("/operations", headers=headers(key=key), json=payload()).status_code == 422
    assert snapshot(database) == before


@pytest.mark.parametrize("key", ["a", "a" * 64, "AZaz09_-"])
def test_valid_key_boundaries(client, key):
    assert client.post("/operations", headers=headers(key=key), json=payload()).status_code == 201


@pytest.mark.parametrize("size,status", [(16383, 201), (16384, 201), (16385, 413)])
@pytest.mark.parametrize("content_length", [None, b"1"])
def test_actual_streamed_byte_boundary_with_misleading_content_length(
    settings, database, size, status, content_length
):
    app = create_app(build_components(settings))
    raw = json.dumps(payload()).encode()
    raw += b" " * (size - len(raw))
    before = snapshot(database)

    async def request():
        # Feed real ASGI messages: TestClient can coalesce a generator into one body.
        chunks = iter(raw[index : index + 1024] for index in range(0, len(raw), 1024))
        sent = []
        received = 0

        async def receive():
            nonlocal received
            chunk = next(chunks)
            received += len(chunk)
            return {"type": "http.request", "body": chunk, "more_body": received < len(raw)}

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/operations",
                "raw_path": b"/operations",
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"authorization", f"Bearer {AGENT_TOKEN}".encode()),
                    (b"idempotency-key", b"stream"),
                    (b"content-type", b"application/json"),
                ]
                + ([(b"content-length", content_length)] if content_length else []),
                "client": ("127.0.0.1", 1),
                "server": ("test", 80),
            },
            receive,
            send,
        )
        return sent

    messages = asyncio.run(request())
    assert messages[0]["status"] == status
    if status == 413:
        assert json.loads(messages[1]["body"]) == {"error": "BODY_TOO_LARGE"}
        assert snapshot(database) == before
    else:
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
            assert (
                connection.execute("SELECT SUM(balance_cents) FROM accounts").fetchone()[0]
                == 2000000
            )


def test_body_limit_counts_utf8_bytes(client, database):
    # Fewer than 16 Ki characters still exceed the byte limit.
    raw = json.dumps({"prompt": "á" * 8200}, ensure_ascii=False)
    assert len(raw) < 16384 < len(raw.encode())
    before = snapshot(database)
    assert client.post("/operations", headers=headers(), content=raw).status_code == 413
    assert snapshot(database) == before
