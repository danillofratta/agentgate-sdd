"""Real HTTP/process acceptance. Run on Linux from the repository root, outside Pytest.

Uses only loopback and disposable storage; prints no credentials or request headers.
"""

import hashlib
import json
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from agentgate.dependencies import build_components
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.money import Money
from agentgate.domain.value_objects.operation_request import OperationRequest
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.features.evaluate_policy.handler import EvaluatePolicyHandler
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.persistence.sqlite_unit_of_work import SqliteUnitOfWork
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from agentgate.infrastructure.security.settings import Settings


def transfer(amount=10001):
    return OperationRequest(
        TransferArguments(AccountId("acct-alice"), AccountId("acct-bob"), Money(amount))
    )


def main():
    assert os.name == "posix", "Run in the documented Linux container for SIGTERM verification"
    directory = Path(tempfile.mkdtemp(prefix="agentgate-e2e-"))
    database = directory / "acceptance.sqlite3"
    agent, approver = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    assert agent != approver
    environment = {
        **os.environ,
        "AGENTGATE_AGENT_TOKEN": agent,
        "AGENTGATE_APPROVER_TOKEN": approver,
        "AGENTGATE_DATABASE": str(database),
    }
    evidence = {"started_at": datetime.now(UTC).isoformat(), "directory": str(directory)}
    responses = []
    http_checks = []
    opener = build_opener(ProxyHandler({}))
    base = "http://127.0.0.1:8000"
    server = None
    server_pid = None
    logs = []

    def http(method, path, token=agent, payload=None, key=None, expected=200):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        request = Request(base + path, data=data, headers=headers, method=method)
        try:
            with opener.open(request, timeout=5) as response:
                status, body = response.status, response.read()
        except HTTPError as error:
            status, body = error.code, error.read()
        assert status == expected, f"Unexpected HTTP status: {method} {path}: {status}"
        value = json.loads(body)
        responses.append(value)
        http_checks.append({"method": method, "path": path, "status": status})
        if status >= 400:
            assert set(value) == {"error"} and isinstance(value["error"], str)
        return value

    def rows(sql, parameters=()):
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            return connection.execute(sql, parameters).fetchall()

    def balances():
        return rows("SELECT id,balance_cents FROM accounts ORDER BY id")

    def snapshot(label):
        target = directory / f"{label}.sqlite3"
        with (
            closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)
            assert destination.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert destination.execute("PRAGMA foreign_key_check").fetchall() == []
            dump = "\n".join(destination.iterdump()).encode()
        return hashlib.sha256(dump).hexdigest()

    def start(number):
        nonlocal server, server_pid
        log = directory / f"server-{number}.log"
        logs.append(log)
        command = [
            "uv",
            "run",
            "--project",
            str(Path(__file__).resolve().parents[2] / "backend/services/agentgate"),
            "--offline",
            "--locked",
            "uvicorn",
            "agentgate.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-access-log",
        ]
        with log.open("wb") as output:
            server = subprocess.Popen(command, env=environment, stdout=output, stderr=output)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert server.poll() is None, "Server exited before readiness"
            try:
                ready = http("GET", "/audit?limit=1", approver)
                text = log.read_text()
                match = re.search(r"Started server process \[(\d+)\]", text)
                if match and "Application startup complete" in text:
                    server_pid = int(match[1])
                    record = {
                        "launcher_pid": server.pid,
                        "server_pid": server_pid,
                        "readiness_status": 200,
                        "simulation": ready["simulation"],
                        "startup_complete": True,
                    }
                    evidence[f"process_{number}"] = record
                    return server_pid
            except URLError:
                pass
            time.sleep(0.05)  # Readiness polling only; concurrency tests use Events.
        raise AssertionError("Server readiness deadline exceeded")

    def stop(number):
        nonlocal server
        os.kill(server_pid, signal.SIGTERM)
        code = server.wait(timeout=15)
        text = logs[-1].read_text()
        assert "Application shutdown complete" in text
        assert f"Finished server process [{server_pid}]" in text
        assert not Path(f"/proc/{server_pid}").exists(), "Old Uvicorn process still exists"
        evidence[f"process_{number}"].update(exit_code=code, graceful_exit=True)
        server = None

    def submit(amount, key, expected=201, reverse=False):
        arguments = {
            "source_account_id": "acct-alice",
            "destination_account_id": "acct-bob",
            "amount_cents": amount,
            "currency": "USD",
        }
        if reverse:
            arguments = dict(reversed(list(arguments.items())))
        return http(
            "POST",
            "/operations",
            payload={"tool": "simulate_transfer", "arguments": arguments},
            key=key,
            expected=expected,
        )

    def no_effect():
        assert balances() == [("acct-alice", 1000000), ("acct-bob", 1000000)]
        assert rows(
            "SELECT COUNT(*) FROM audit_events WHERE event_type IN "
            "('OPERATION_DISPATCHED','OPERATION_EXECUTED')"
        ) == [(0,)]

    try:
        subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(Path(__file__).resolve().parents[2] / "backend/services/agentgate"),
                "--offline",
                "--locked",
                "python",
                "-m",
                "agentgate.infrastructure.persistence.seed",
                "--database",
                str(database),
            ],
            env=environment,
            check=True,
            capture_output=True,
        )
        no_effect()
        evidence["initial_balances"] = balances()
        # Additional fixtures use existing handlers, never HTTP identity overrides.
        settings = Settings(agent, approver, str(database))
        components = build_components(settings)
        principal = components.credentials.verify(agent)
        foreign = replace(principal, id=PrincipalId("principal-other"))
        old_clock = SimpleNamespace(now=lambda: datetime.now(UTC) - timedelta(seconds=600))
        requester = RequestOperationHandler(
            lambda: SqliteUnitOfWork(str(database)),
            EvaluatePolicyHandler(),
            old_clock,
            UuidOperationIdGenerator(),
        )
        foreign_id = requester.handle(
            RequestOperationCommand(foreign, IdempotencyKey("fixture-foreign"), transfer(1))
        ).operation.id.value
        expired_id = requester.handle(
            RequestOperationCommand(
                principal, IdempotencyKey("fixture-expired-pending"), transfer()
            )
        ).operation.id.value
        first_pid = start(1)
        keys = ["accept-" + secrets.token_hex(12) for _ in range(3)]
        allowed = submit(1, keys[0])
        denied = submit(100001, keys[1])
        pending = submit(10001, keys[2])
        evidence["policy_decisions"] = [
            {"id": op["id"], "decision": op["decision"], "state": op["state"]}
            for op in (allowed, denied, pending)
        ]
        assert [op["decision"] for op in (allowed, denied, pending)] == [
            "ALLOW",
            "DENY",
            "REQUIRE_APPROVAL",
        ]
        for operation in (allowed, denied, pending):
            stored = rows("SELECT decision FROM operations WHERE id=?", (operation["id"],))
            assert stored == [(operation["decision"],)]
        assert rows("SELECT COUNT(*) FROM approvals WHERE operation_id=?", (denied["id"],)) == [
            (0,)
        ]
        http("POST", f"/operations/{denied['id']}/execute", expected=403)
        path = f"/operations/{pending['id']}"
        http("POST", path + "/execute", expected=409)
        no_effect()
        http("POST", path + "/approval", payload={"decision": "APPROVE"}, expected=403)
        grant = http("POST", path + "/approval", approver, {"decision": "APPROVE"})
        assert grant["approval_state"] == "GRANTED"
        binding = rows(
            "SELECT a.principal_id=a2.principal_id,a.fingerprint=a2.fingerprint,"
            "a.policy_version=a2.policy_version,a.created_at=a2.created_at,"
            "a2.approver_id,a2.status "
            "FROM operations a JOIN approvals a2 ON a.id=a2.operation_id WHERE a.id=?",
            (pending["id"],),
        )
        assert binding == [(1, 1, 1, 1, "principal-approver", "GRANTED")]
        no_effect()
        result = http("POST", path + "/execute")
        assert result["state"] == "SUCCEEDED" and result["simulation"] is True
        assert result["decision"] == "REQUIRE_APPROVAL"
        assert result["effective_decision"] == "ALLOW"
        assert result["effective_reason"] == "HUMAN_APPROVED"
        assert result["result"]["amount_cents"] == 10001
        expected_balances = [("acct-alice", 989999), ("acct-bob", 1010001)]
        assert balances() == expected_balances and sum(v for _, v in balances()) == 2000000
        committed = snapshot("committed")
        assert http("POST", path + "/execute") == result
        replay = submit(10001, keys[2], expected=200, reverse=True)
        assert replay["id"] == result["id"] and replay["result"] == result["result"]
        submit(10002, keys[2], expected=409)
        http("POST", path + "/approval", approver, {"decision": "APPROVE"}, expected=409)
        http(
            "POST",
            "/operations",
            payload={"tool": "rejected-raw-sentinel\nINJECT"},
            key="reject-sentinel",
            expected=422,
        )
        assert snapshot("after-replays") == committed

        def query_checks(label):
            before = snapshot(label + "-before")
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as monitor:
                version = monitor.execute("PRAGMA data_version").fetchone()
                for _ in range(3):
                    view = http("GET", path)
                    assert view["state"] == "SUCCEEDED" and view["result"] == result["result"]
                    assert view["simulation"] is True
                    assert view["approval"]["state"] == "CONSUMED"
                    assert http("GET", path, approver) == view
                    http("GET", f"/operations/{foreign_id}", expected=404)
                    assert http("GET", f"/operations/{foreign_id}", approver)["state"] == "READY"
                    expired = http("GET", f"/operations/{expired_id}")["approval"]
                    assert expired["state"] == "PENDING"
                    assert datetime.fromisoformat(expired["expires_at"]) < datetime.now(UTC)
                    http("GET", "/audit", expected=403)
                    http("GET", "/audit", token=None, expected=401)
                    http("GET", "/audit?limit=101", approver, expected=422)
                    audit = http("GET", "/audit?limit=100", approver)
                    assert audit["simulation"] is True
                    events = [e for e in audit["events"] if e["operation_id"] == result["id"]]
                    assert [e["event_type"] for e in events] == [
                        "OPERATION_REQUESTED",
                        "APPROVAL_DECIDED",
                        "OPERATION_ATTEMPTED",
                        "OPERATION_DISPATCHED",
                        "OPERATION_EXECUTED",
                    ]
                    assert events[1]["approver_id"] == "principal-approver"
                    assert (
                        events[1]["fingerprint"]
                        == rows("SELECT fingerprint FROM operations WHERE id=?", (result["id"],))[
                            0
                        ][0]
                    )
                    assert events[2]["attempt"] == 1
                    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
                    for event in audit["events"]:
                        assert set(event) == {
                            "id",
                            "operation_id",
                            "principal_id",
                            "tool",
                            "decision",
                            "reason",
                            "policy_version",
                            "occurred_at",
                            "event_type",
                            "approver_id",
                            "fingerprint",
                            "attempt",
                        }
                    assert (
                        http("GET", f"/audit?after={audit['next_after']}&limit=100", approver)[
                            "events"
                        ]
                        == []
                    )
                assert monitor.execute("PRAGMA data_version").fetchone() == version
            after = snapshot(label + "-after")
            assert before == after == committed
            evidence[label] = {
                "before_sha256": before,
                "after_sha256": after,
                "data_version_unchanged": True,
                "repetitions": 3,
            }
            return events, view

        events, view = query_checks("queries")
        stop(1)
        second_pid = start(2)
        assert second_pid != first_pid
        assert http("GET", path) == view
        assert http("POST", path + "/execute") == result
        assert submit(10001, keys[2], expected=200)["result"] == result["result"]
        restarted_events, _ = query_checks("restart-queries")
        assert restarted_events == events
        assert rows(
            "SELECT event_type,COUNT(*) FROM audit_events WHERE event_type IN "
            "('OPERATION_EXECUTED','OPERATION_DISPATCHED') GROUP BY event_type"
        ) == [("OPERATION_DISPATCHED", 1), ("OPERATION_EXECUTED", 1)]
        assert rows("SELECT COUNT(*) FROM operations WHERE state='SUCCEEDED'") == [(1,)]
        assert balances() == expected_balances
        stop(2)
        evidence.update(
            operation_id=result["id"],
            original_decision=result["decision"],
            final_balances=balances(),
            lifecycle=events,
            result=result,
            approval_binding_verified=True,
            replay_unchanged=True,
            expired_pending_read_unchanged=True,
            ownership_http_404=True,
            successful_dispatches=1,
            successful_transfers=1,
            final_snapshot_sha256=snapshot("final"),
        )
        sensitive = [
            agent,
            approver,
            "rejected-raw-sentinel",
            "INJECT",
            "Bearer ",
            "Authorization",
            "Traceback",
        ]
        inspected = json.dumps(responses) + json.dumps(evidence)
        inspected += "".join(log.read_text() for log in logs)
        inspected += database.read_bytes().decode("latin1")
        assert all(value not in inspected for value in sensitive), "Sensitive evidence detected"
        evidence["sanitization_passed"] = True
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        (directory / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        (directory / "http-checks.json").write_text(json.dumps(http_checks, indent=2) + "\n")
        print(json.dumps(evidence, indent=2))
    finally:
        if server is not None and server.poll() is None:
            os.kill(server_pid or server.pid, signal.SIGTERM)
            server.wait(timeout=15)


if __name__ == "__main__":
    main()
