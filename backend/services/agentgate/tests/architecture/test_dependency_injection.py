import sqlite3
from types import SimpleNamespace

import pytest

from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.reason import Reason
from agentgate.domain.value_objects.idempotency_key import IdempotencyKey
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.features.request_operation.command import RequestOperationCommand
from agentgate.features.request_operation.handler import RequestOperationHandler
from agentgate.infrastructure.runtime.system_clock import SystemClock
from agentgate.infrastructure.runtime.uuid_operation_id_generator import UuidOperationIdGenerator
from tests.application.test_request_handler import FakeUnitOfWork
from tests.architecture.rules import inspect_organization, inspect_sources
from tests.architecture.test_cqrs import feature_sources
from tests.domain.test_request_values import transfer


def injected_sources(annotation="OperationRepository", default=""):
    sources = feature_sources()
    sources["agentgate/domain/repositories/operation_repository.py"] = (
        "from typing import Protocol as Contract\n"
        "class OperationRepository(Contract):\n    def save(self, operation): ..."
    )
    sources["agentgate/features/sample/handler.py"] = (
        "from .command import SampleCommand\n"
        "from agentgate.domain.repositories.operation_repository import OperationRepository\n"
        "class SampleHandler:\n"
        f"    def __init__(self, repository: {annotation}{default}):\n"
        "        self.repository = repository\n"
        "    def handle(self, request: SampleCommand):\n"
        "        self.repository.save(request)\n"
    )
    return sources


def test_typed_constructor_injection_and_aliased_protocol_are_allowed():
    sources = injected_sources()
    assert inspect_sources(sources) == []
    assert inspect_organization(sources) == []


@pytest.mark.parametrize("annotation", ["object", "'object'", "Any"])
def test_untyped_collaborators_are_rejected(annotation):
    errors = inspect_sources(injected_sources(annotation))
    assert any("constructor collaborators" in error for error in errors)


@pytest.mark.parametrize("default", [" = OperationRepository()", " = global_repository"])
def test_constructors_cannot_capture_default_dependencies(default):
    errors = inspect_sources(injected_sources(default=default))
    assert any("hidden default" in error for error in errors)


def test_explicit_optional_port_can_be_injected_without_constructing_a_fallback():
    assert inspect_sources(injected_sources(default=" = None")) == []


@pytest.mark.parametrize(
    "hidden",
    [
        "container = dict()",
        "services = {}",
        "registry = SimpleNamespace()",
        "global_dependencies = SimpleNamespace()",
        "container = build_container()",
        "repository = container.get('repository')",
        "repository = service_locator.get('repository')",
        "repository = get_repository()",
        "repository = get_components()",
        "from fastapi import Depends as Inject\nrepository = Inject(get_repository)",
        "from dependency_injector.wiring import inject\n@inject\ndef resolve(): pass",
    ],
)
def test_hidden_dependency_resolution_and_framework_di_are_rejected(hidden):
    sources = injected_sources()
    sources["agentgate/features/sample/handler.py"] += "\n" + hidden
    assert inspect_sources(sources)


@pytest.mark.parametrize(
    "constructor", ["SqliteOperationRepository", "LocalCredentialGateway", "OperationRepository"]
)
def test_handlers_cannot_construct_collaborators(constructor):
    sources = injected_sources()
    sources["agentgate/features/sample/handler.py"] += f"\nrepository = {constructor}()"
    assert any("constructed outside composition" in error for error in inspect_sources(sources))


def test_handler_cannot_replace_injected_port_with_a_concrete_adapter():
    sources = injected_sources()
    path = "agentgate/features/sample/handler.py"
    sources[path] = sources[path].replace(
        "self.repository = repository", "self.repository = SqliteOperationRepository(connection)"
    )
    assert any("constructed outside composition" in error for error in inspect_sources(sources))


def test_adapter_construction_is_allowed_only_at_the_composition_root():
    source = (
        "from agentgate.infrastructure.repositories.sqlite_operation_repository "
        "import SqliteOperationRepository as Adapter\nrepository = Adapter(connection)"
    )
    assert inspect_sources({"agentgate/dependencies.py": source}) == []
    for path in ("agentgate/features/sample/handler.py", "agentgate/components.py"):
        assert inspect_sources({path: source})


@pytest.mark.parametrize(
    "import_statement",
    [
        "import fastapi",
        "from fastapi import Request as HTTPRequest",
        "import pydantic as validation",
        "from sqlalchemy.orm import Session",
        "import agentgate.infrastructure.persistence.database as db",
        "from ..infrastructure import persistence",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n import sqlalchemy",
    ],
)
def test_domain_cannot_import_frameworks_or_adapters(import_statement):
    errors = inspect_sources({"agentgate/domain/operation.py": import_statement})
    assert any("domain purity" in error for error in errors)


def test_domain_prefix_does_not_allow_other_packages():
    assert inspect_sources(
        {"agentgate/domain/operation.py": "import agentgate.domain_extra.adapter"}
    )


@pytest.mark.parametrize(
    "dependency",
    [
        "from fastapi import Depends",
        "from pydantic import BaseModel",
        "from agentgate.infrastructure.repositories import sqlite_operation_repository",
    ],
)
def test_framework_or_concrete_handler_dependencies_fail(dependency):
    sources = injected_sources()
    sources["agentgate/features/sample/handler.py"] += "\n" + dependency
    assert inspect_sources(sources)


@pytest.mark.parametrize(
    "path,source,expected",
    [
        (
            "agentgate/application/ports/operation_repository.py",
            "from typing import Protocol\nclass OperationRepository(Protocol): pass",
            "domain/repositories",
        ),
        (
            "agentgate/domain/repositories/credential_gateway.py",
            "from typing import Protocol\nclass CredentialGateway(Protocol): pass",
            "application/ports",
        ),
        (
            "agentgate/infrastructure/gateways/credential.py",
            "class Credential: pass",
            "Gateway suffix",
        ),
        (
            "agentgate/infrastructure/security/local_credential_gateway.py",
            "class LocalCredentialGateway: pass",
            "infrastructure/gateways",
        ),
        (
            "agentgate/infrastructure/gateways/sqlite_operation_repository.py",
            "class SqliteOperationRepository: pass",
            "infrastructure/repositories",
        ),
        (
            "agentgate/infrastructure/gateways/base_gateway.py",
            "class BaseGateway: pass",
            "generic adapter",
        ),
    ],
)
def test_repository_and_gateway_contract_adapter_conventions(path, source, expected):
    assert any(expected in error for error in inspect_organization({path: source}))


def test_gateway_contract_and_adapter_naming_is_allowed():
    contract = (
        "from typing import Protocol\nclass CredentialGateway(Protocol):\n def verify(self): ..."
    )
    adapter = "class LocalCredentialGateway:\n def verify(self): pass"
    sources = {
        "agentgate/application/ports/credential_gateway.py": contract,
        "agentgate/infrastructure/gateways/local_credential_gateway.py": adapter,
    }
    assert inspect_sources(sources) == []
    assert inspect_organization(sources) == []


def test_request_handler_uses_only_the_injected_ports(monkeypatch, principal, clock):
    def forbidden(*args, **kwargs):
        pytest.fail("Concrete dependency was used instead of the injected port")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(SystemClock, "now", forbidden)
    monkeypatch.setattr(UuidOperationIdGenerator, "next_id", forbidden)
    work = FakeUnitOfWork()
    observed = []

    def policy(snapshot):
        observed.append(snapshot)
        return PolicyDecision(Decision.DENY, Reason.POLICY_UNCERTAIN, PolicyVersion("v1"))

    use_case = RequestOperationHandler(
        lambda: work,
        SimpleNamespace(evaluate=policy),
        clock,
        SimpleNamespace(next_id=lambda: "00000000-0000-4000-8000-000000000001"),
    )
    result = use_case.handle(
        RequestOperationCommand(principal, IdempotencyKey("di-test"), transfer())
    )
    assert result.operation.policy.decision == Decision.DENY
    assert result.operation.created_at == clock.now()
    assert observed[0].principal == principal
    assert work.commits == len(work.events) == 1
    assert not work.pending
