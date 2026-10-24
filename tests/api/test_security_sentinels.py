"""Task 6.3: inspect every output channel without rendering sentinel values.

PYTEST_DONT_REWRITE: metadata assertions must never echo compromised values.
"""

import json
import logging
import sqlite3
import unicodedata
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.deadline_connection import DeadlineConnection
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.security.settings import Settings
from tests.api.test_adversarial_api import dispatches as dispatches
from tests.api.test_full_api_integration import api as lifecycle_api  # noqa: F401
from tests.api.test_full_api_integration import approve, balances, execute, submit
from tests.api.test_request_endpoint import headers, payload
from tests.api.test_strict_input import snapshot

AGENT = "sentinel-agent-6c3-a81e4d795b023f67"
APPROVER = "sentinel-approver-6c3-d295e4a71b86"
INVALID = "sentinel-invalid-6c3-e7d513a924b8"
SENSITIVE = "sentinel-sensitive-6c3-b93e1d7a52f4"
FORGED = "FORGED_EVENT_6C3"
INTERNAL = "SELECT private_value FROM private_credentials; Traceback (most recent call last)"
CONTROLS = ("\r", "\n", "\t", "\x00", "\x1b", "\x85", "\u2028", "\u2029", "\u202e", "\u2066")


@pytest.fixture
def settings(database):
    # Reuse the HTTP lifecycle fixture with distinct credentials for this suite.
    return Settings(AGENT, APPROVER, database)


@pytest.fixture
def api(lifecycle_api, monkeypatch):  # noqa: F811
    # Existing lifecycle helpers use the shared fixture tokens. Translate only at
    # the client boundary; the real credential gateway still checks our sentinels.
    from tests.conftest import AGENT_TOKEN, APPROVER_TOKEN

    api = lifecycle_api
    request = api.request

    def recorded_request(method, url, **kwargs):
        auth = kwargs.get("headers", {})
        for old, new in ((AGENT_TOKEN, AGENT), (APPROVER_TOKEN, APPROVER)):
            if auth.get("Authorization") == f"Bearer {old}":
                kwargs["headers"] = {**auth, "Authorization": f"Bearer {new}"}
        return request(method, url, **kwargs)

    monkeypatch.setattr(api, "request", recorded_request)
    return api


def safe(condition, message):
    """Never include inspected values in assertion introspection or CI output."""
    if not condition:
        pytest.fail(message, pytrace=False)


def no_leaks(value):
    rendered = str(value)
    markers = (
        AGENT,
        APPROVER,
        INVALID,
        SENSITIVE,
        FORGED,
        INTERNAL,
        "Traceback",
        "private_credentials",
    )
    safe(not any(marker in rendered for marker in markers), "Sensitive output detected")


@pytest.fixture
def channels(api, database, caplog, capsys, monkeypatch, request):
    caplog.set_level(logging.DEBUG)
    responses = []
    send = api.request
    add_section = request.node.add_report_section

    def safe_section(when, key, content):
        # Pytest otherwise echoes captured secrets if a containment assertion fails.
        if key not in {"log", "stdout", "stderr"}:
            add_section(when, key, content)

    monkeypatch.setattr(request.node, "add_report_section", safe_section)

    def observed_request(*args, **kwargs):
        response = send(*args, **kwargs)
        responses.append(response)
        return response

    monkeypatch.setattr(api, "request", observed_request)

    def inspect(response):
        responses.append(response)
        return response

    yield inspect
    # Clear captured logs BEFORE any assertion: pytest's automatic failure report
    # must not echo a leaked credential, including from a third-party logger.
    records = list(caplog.records)
    caplog.clear()
    captured = capsys.readouterr()
    for response in responses:
        no_leaks((response.text, tuple(response.headers.multi_items())))
    for record in records:
        no_leaks((record.__dict__, record.getMessage(), record.exc_text))
        safe(record.exc_info is None, "Unexpected traceback in operational log")
    no_leaks((captured.out, captured.err))
    # There is currently no application logger. In particular, untrusted strings
    # must not manufacture trusted records or metadata in any application logger.
    safe(not any(r.name.startswith("agentgate") for r in records), "Unexpected application event")
    stored = snapshot(database)
    no_leaks(stored)
    for table in stored:
        for row in table:
            for value in row:
                if isinstance(value, str):
                    safe(
                        not any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in value),
                        "Control character persisted",
                    )


def audit_rows(database):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT id, operation_id, principal_id, event_type, reason, occurred_at "
            "FROM audit_events ORDER BY id"
        ).fetchall()


@pytest.mark.parametrize(
    "case", ["valid_agent", "valid_approver", "invalid", "basic", "empty", "extra", "tab"]
)
def test_bearer_sentinels_keep_authorization_and_all_channels_clean(
    api, database, dispatches, channels, case
):
    operation = submit(api, 10001)
    before = snapshot(database)
    auth = {
        "valid_agent": f"Bearer {AGENT}",
        "valid_approver": f"Bearer {APPROVER}",
        "invalid": f"Bearer {INVALID}",
        "basic": f"Basic {INVALID}",
        "empty": "Bearer",
        "extra": f"Bearer {INVALID} extra",
        "tab": f"Bearer\t{INVALID}",
    }[case]
    response = channels(api.get("/audit", headers={"Authorization": auth}))
    expected = 200 if case == "valid_approver" else 403 if case == "valid_agent" else 401
    assert response.status_code == expected
    if expected == 401:
        assert response.headers["www-authenticate"] == "Bearer"
    safe(snapshot(database) == before, "Authentication changed durable data")
    assert dispatches == []
    assert operation["decision"] == "REQUIRE_APPROVAL"


@pytest.mark.parametrize("control", range(len(CONTROLS)))
@pytest.mark.parametrize(
    "location", ["field", "field_name", "key", "authorization", "approval", "execute"]
)
def test_log_injection_cannot_create_events_or_override_metadata(
    api, database, dispatches, channels, control, location
):
    operation = submit(api, 10001)
    before = snapshot(database)
    attack = (
        SENSITIVE
        + CONTROLS[control]
        + json.dumps(
            {
                "timestamp": "1900-01-01T00:00:00Z",
                "level": "CRITICAL",
                "event_id": FORGED,
                "operation_id": FORGED,
                "correlation_id": FORGED,
                "principal_id": "principal-approver",
            }
        )
    )
    body, auth, url = payload(), headers("injection"), "/operations"
    if location == "field":
        body["arguments"]["source_account_id"] = attack
    elif location == "field_name":
        body[attack] = attack
    elif location == "key":
        auth["Idempotency-Key"] = attack.encode("utf-8")
    elif location == "authorization":
        # HTTPX requires byte headers for non-ASCII ASGI adversarial input.
        auth["Authorization"] = ("Bearer " + attack).encode("utf-8")
    else:
        url = f"/operations/{operation['id']}/{location}"
        body = {"decision": attack} if location == "approval" else {"arguments": attack}
        if location == "approval":
            auth = headers(token=APPROVER)
    response = channels(api.post(url, headers=auth, json=body))
    assert response.status_code == (401 if location == "authorization" else 422)
    safe(snapshot(database) == before, "Rejected injection changed durable state")
    assert dispatches == []
    rows = audit_rows(database)
    safe(len(rows) == 1, "Injected audit event")
    assert rows[0][0:5] == (
        1,
        operation["id"],
        "principal-agent",
        "OPERATION_REQUESTED",
        "APPROVAL_REQUIRED",
    )


@pytest.mark.parametrize("boundary", ["submission", "execution", "tool", "unexpected"])
def test_exception_messages_are_contained_across_channels(
    api, database, clock, dispatches, channels, boundary
):
    def fail(*args):
        raise RuntimeError(SENSITIVE + "\n" + INTERNAL + FORGED + AGENT + APPROVER)

    components = api.app.state.components
    before = balances(database)
    if boundary == "submission":
        handler = RequestOperationHandler(
            lambda: SqliteUnitOfWork(database),
            SimpleNamespace(evaluate=fail),
            clock,
            UuidOperationIdGenerator(),
        )
        api.app.state.components = replace(components, request_operation=handler)
        response = channels(api.post("/operations", headers=headers(), json=payload()))
        assert response.status_code == 201
        operation = response.json()
        assert (operation["decision"], operation["reason"]) == ("DENY", "POLICY_UNCERTAIN")
        assert channels(execute(api, operation)).status_code == 403
        assert audit_rows(database)[0][4] == "POLICY_UNCERTAIN"
    elif boundary == "execution":
        operation = submit(api)
        components.execute_operation._harness._policy = SimpleNamespace(evaluate=fail)
        assert channels(execute(api, operation)).status_code == 403
    elif boundary == "tool":
        operation = submit(api)
        calls = []

        def failed_tool(*args):
            calls.append(1)
            fail()

        components.execute_operation._harness._tools = SimpleNamespace(dispatch=failed_tool)
        response = channels(execute(api, operation))
        assert response.status_code == 200
        assert response.json()["state"] == "FAILED"
        assert response.json()["result"] is None
        assert channels(execute(api, operation)).json() == response.json()
        assert calls == [1]
    else:
        api.app.state.components = replace(
            components, request_operation=SimpleNamespace(handle=fail)
        )
        stored = snapshot(database)
        response = channels(api.post("/operations", headers=headers(), json=payload()))
        assert response.status_code == 500
        safe(response.json() == {"error": "INTERNAL_ERROR"}, "Unsafe internal error response")
        safe(snapshot(database) == stored, "Unexpected exception changed state")
    assert balances(database) == before
    assert dispatches == []


@pytest.mark.parametrize(
    "boundary", ["audit_rollback", "unavailable", "uncertain_rollback", "uncertain_committed"]
)
def test_sqlite_sensitive_errors_preserve_rollback_and_recovery(
    api, database, monkeypatch, dispatches, channels, boundary
):
    operation = submit(api, 10001)
    assert approve(api, operation).status_code == 200
    before = balances(database)
    execute_sql = DeadlineConnection.execute
    commit = DeadlineConnection.commit

    def fail_sql(connection, sql, parameters=()):
        if boundary == "unavailable" or (
            boundary == "audit_rollback" and "OPERATION_EXECUTED" in parameters
        ):
            raise sqlite3.OperationalError(SENSITIVE + "\n" + INTERNAL)
        return execute_sql(connection, sql, parameters)

    def fail_commit(connection):
        state = sqlite3.Connection.execute(connection, "SELECT state FROM operations").fetchone()[0]
        if state != "SUCCEEDED":
            return commit(connection)
        if boundary == "uncertain_committed":
            commit(connection)
        raise sqlite3.OperationalError(SENSITIVE + "\n" + INTERNAL)

    with monkeypatch.context() as fault:
        if boundary.startswith("uncertain"):
            fault.setattr(DeadlineConnection, "commit", fail_commit)
        else:
            fault.setattr(DeadlineConnection, "execute", fail_sql)
        response = channels(execute(api, operation))
    committed = boundary == "uncertain_committed"
    assert response.status_code == (200 if committed else 503)
    if not committed:
        safe(response.json() == {"error": "STORAGE_UNAVAILABLE"}, "Unsafe storage response")
        assert balances(database) == before
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT status FROM approvals").fetchone()[0] == "GRANTED"
            assert connection.execute("SELECT result_json FROM operations").fetchone()[0] is None
    assert len(dispatches) == (0 if boundary == "unavailable" else 1)
    recovered = channels(execute(api, operation))
    assert recovered.status_code == 200
    if boundary == "audit_rollback":
        assert recovered.json()["state"] == "FAILED"
        assert balances(database) == before
        assert len(dispatches) == 1
        assert [row[3] for row in audit_rows(database)] == [
            "OPERATION_REQUESTED",
            "APPROVAL_DECIDED",
            "OPERATION_ATTEMPTED",
            "OPERATION_FAILED",
        ]
        return
    assert recovered.json()["state"] == "SUCCEEDED"
    assert len(dispatches) == (1 if committed or boundary == "unavailable" else 2)
    assert balances(database) == [("acct-alice", 989999), ("acct-bob", 1010001)]
    rows = audit_rows(database)
    assert sum(row[3] == "OPERATION_EXECUTED" for row in rows) == 1
    safe(all(row[1] == operation["id"] for row in rows), "Broken operation correlation")


def test_success_and_rejection_audit_sentinels_and_read_only_inspection(
    api, database, dispatches, channels, clock
):
    success = submit(api, 10001, "success")
    assert channels(approve(api, success)).status_code == 200
    assert channels(execute(api, success)).status_code == 200
    rejected = submit(api, 10001, "rejected")
    assert channels(approve(api, rejected, "REJECT")).status_code == 200
    denied = submit(api, 100001, "denied")
    assert channels(execute(api, denied)).status_code == 403
    stored = snapshot(database)
    for _ in range(2):
        for operation in (success, rejected, denied):
            assert (
                channels(api.get(f"/operations/{operation['id']}", headers=headers())).status_code
                == 200
            )
        response = channels(api.get("/audit", headers=headers(token=APPROVER)))
        assert response.status_code == 200
    safe(snapshot(database) == stored, "Inspection mutated durable state")
    rows = audit_rows(database)
    assert [row[0] for row in rows] == list(range(1, 9))
    assert [row[3] for row in rows] == [
        "OPERATION_REQUESTED",
        "APPROVAL_DECIDED",
        "OPERATION_ATTEMPTED",
        "OPERATION_DISPATCHED",
        "OPERATION_EXECUTED",
        "OPERATION_REQUESTED",
        "APPROVAL_DECIDED",
        "OPERATION_REQUESTED",
    ]
    safe(all(row[5] == clock.now().isoformat() for row in rows), "Untrusted audit timestamp")
    assert len(dispatches) == 1


@pytest.mark.parametrize("marker", range(8))
def test_sentinel_assertion_failure_does_not_render_inspected_values(marker):
    values = (
        AGENT,
        APPROVER,
        INVALID,
        SENSITIVE,
        FORGED,
        INTERNAL,
        "Traceback",
        "private_credentials",
    )
    with pytest.raises(pytest.fail.Exception) as caught:
        no_leaks({"untrusted": values[marker]})
    safe(str(caught.value) == "Sensitive output detected", "Unsafe sentinel assertion diagnostic")
