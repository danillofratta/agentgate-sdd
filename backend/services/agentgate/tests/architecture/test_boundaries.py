import ast
from pathlib import Path

import pytest

from tests.architecture.rules import inspect_organization, inspect_sources


def test_actual_package_dependencies_point_inward():
    root = Path(__file__).resolve().parents[2] / "src"
    sources = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    }
    assert inspect_sources(sources) == []
    assert inspect_organization(sources) == []


def test_no_obsolete_or_centralized_endpoint_directories():
    root = Path(__file__).resolve().parents[2] / "src" / "agentgate"
    assert not (root / "api").exists()
    assert not (root / "application" / "features").exists()
    assert not (root / "infrastructure" / "audit").exists()
    assert not any(path.name in {"routes", "controllers"} for path in root.rglob("*"))
    assert not list((root / "application" / "ports").glob("*repository.py"))
    assert (root / "features/request_operation/endpoint.py").is_file()
    assert (root / "features/request_operation/models.py").is_file()
    assert not (root / "features/evaluate_policy/endpoint.py").exists()


def test_bootstrap_only_initializes_and_registers():
    path = Path(__file__).resolve().parents[2] / "src/agentgate/main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)] == [
        "create_app"
    ]
    assert not any(isinstance(node, ast.ClassDef) for node in ast.walk(tree))


@pytest.mark.parametrize(
    "path,source,expected",
    [
        ("agentgate/api/routes/operations.py", "", "centralized endpoint"),
        ("agentgate/controllers/operations.py", "", "centralized endpoint"),
        ("agentgate/endpoints/request.py", "router = APIRouter()", "routers belong"),
        ("agentgate/main.py", "@app.post('/operations')\ndef request(): pass", "endpoints belong"),
        ("agentgate/main.py", "app.add_api_route('/operations', handler)", "endpoints belong"),
        (
            "agentgate/application/ports/operation_repository.py",
            "from typing import Protocol\nclass OperationRepository(Protocol): pass",
            "domain/repositories",
        ),
        (
            "agentgate/features/request_operation/models.py",
            "class Operation: pass",
            "only HTTP schemas",
        ),
        (
            "agentgate/domain/value_objects/money.py",
            "class Money: pass\nclass Currency: pass",
            "one class per file",
        ),
        (
            "agentgate/domain/policies/operation_policy.py",
            "class OperationPolicy: pass\nclass Other: pass",
            "one class per file",
        ),
    ],
)
def test_authoritative_layout_negative_fixtures(path, source, expected):
    assert any(expected in issue for issue in inspect_organization({path: source}))


@pytest.mark.parametrize(
    "source",
    [
        "from fastapi import Request",
        "import pydantic as schemas",
        "from .models import OperationBody",
    ],
)
def test_handlers_cannot_import_http_even_from_their_own_slice(source):
    assert inspect_sources({"agentgate/features/request_operation/handler.py": source})


def test_feature_local_http_grouping_and_endpoint_are_allowed():
    schemas = (
        "from pydantic import BaseModel\nclass One(BaseModel): pass\nclass Two(BaseModel): pass"
    )
    endpoint = "router = APIRouter()\n@router.post('/operations')\ndef request(): pass"
    feature = "agentgate/features/request_operation/"
    assert (
        inspect_organization(
            {
                feature + "models.py": schemas,
                feature + "endpoint.py": endpoint,
                feature + "command.py": "class RequestOperationCommand: pass",
                feature + "handler.py": "class RequestOperationHandler: pass",
            }
        )
        == []
    )


@pytest.mark.parametrize(
    "path,source,expected",
    [
        (
            "agentgate/domain/entities/operation.py",
            "class Operation: pass\nclass Account: pass",
            "one class per file",
        ),
        ("agentgate/domain/value_objects/models.py", "class Money: pass", "grouped generic"),
        ("agentgate/domain/entities/wrong.py", "class Operation: pass", "operation.py"),
        ("agentgate/domain/entities/__init__.py", "class Operation: pass", "operation.py"),
        (
            "agentgate/features/request_operation/command.py",
            "class RequestOperationQuery: pass",
            "query.py",
        ),
        (
            "agentgate/domain/repositories/i_operation_repository.py",
            "from typing import Protocol\nclass IOperationRepository(Protocol): pass",
            "generic port",
        ),
        (
            "agentgate/application/ports/base_gateway.py",
            "from typing import Protocol\nclass BaseGateway(Protocol): pass",
            "generic port",
        ),
        (
            "agentgate/domain/repositories/audit_writer.py",
            "from typing import Protocol\nclass AuditWriter(Protocol):\n def append(self): ...",
            "requires Repository",
        ),
        (
            "agentgate/domain/repositories/operation_gateway.py",
            "from typing import Protocol\nclass OperationGateway(Protocol):\n def find(self): ...",
            "requires Repository",
        ),
        (
            "agentgate/application/ports/credential_repository.py",
            "from typing import Protocol\n"
            "class CredentialRepository(Protocol):\n def verify(self): ...",
            "requires Gateway",
        ),
        (
            "agentgate/application/ports/audit_gateway.py",
            "from typing import Protocol\nclass AuditGateway(Protocol):\n def publish(self): ...",
            "requires EventPublisher",
        ),
        (
            "agentgate/domain/repositories/operation_repository.py",
            "class OperationRepository: pass",
            "Protocol or ABC",
        ),
    ],
)
def test_organization_negative_fixtures(path, source, expected):
    assert any(expected in violation for violation in inspect_organization({path: source}))


def test_organization_positive_fixtures():
    repository = (
        "from typing import Protocol\nclass OperationRepository(Protocol):\n def find(self): ..."
    )
    gateway = "from abc import ABC\nclass CredentialGateway(ABC):\n def verify(self): ..."
    publisher = (
        "from typing import Protocol\nclass AuditEventPublisher(Protocol):\n def publish(self): ..."
    )
    assert (
        inspect_organization(
            {
                "agentgate/domain/entities/operation.py": "class Operation: pass",
                "agentgate/domain/repositories/operation_repository.py": repository,
                "agentgate/application/ports/credential_gateway.py": gateway,
                "agentgate/application/ports/audit_event_publisher.py": publisher,
            }
        )
        == []
    )


@pytest.mark.parametrize(
    "path,source,rule",
    [
        ("agentgate/domain/entities/x.py", "import pydantic as validation", "domain purity"),
        ("agentgate/domain/entities/x.py", "import sqlite3", "domain I/O"),
        ("agentgate/domain/entities/x.py", "from os import environ as env", "domain I/O"),
        (
            "agentgate/domain/entities/x.py",
            "from datetime import datetime as dt\ndt.now()",
            "clock",
        ),
        ("agentgate/domain/entities/x.py", "from ...infrastructure import store", "domain purity"),
        (
            "agentgate/features/request_operation/handler.py",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n from agentgate.api import app",
            "inward application",
        ),
        (
            "agentgate/application/ports/__init__.py",
            "from agentgate.infrastructure import persistence as exported",
            "inward application",
        ),
        (
            "agentgate/features/request_operation/handler.py",
            "from ..execute_operation import handler",
            "sibling slice",
        ),
        (
            "agentgate/infrastructure/repositories/x.py",
            "from agentgate.features.request_operation import handler",
            "adapter depends",
        ),
        (
            "agentgate/features/request_operation/endpoint.py",
            "from agentgate.infrastructure import persistence",
            "outside composition",
        ),
        (
            "agentgate/features/request_operation/endpoint.py",
            "db.execute('SELECT 1')",
            "SQL outside",
        ),
        (
            "agentgate/features/request_operation/handler.py",
            "db.execute('SELECT 1')",
            "SQL outside",
        ),
        (
            "agentgate/features/request_operation/handler.py",
            "container.resolve('db')",
            "hidden dependency",
        ),
        (
            "agentgate/features/request_operation/handler.py",
            "services = {}",
            "mutable application global",
        ),
        (
            "agentgate/features/request_operation/handler.py",
            "Depends(get_database)",
            "hidden dependency",
        ),
        (
            "agentgate/features/request_operation/endpoint.py",
            "tools.dispatch('simulate_transfer')",
            "dispatch outside",
        ),
        ("agentgate/domain/entities/x.py", "eval('bad')", "dynamic execution"),
        (
            "agentgate/features/request_operation/endpoint.py",
            "import importlib\nimportlib.import_module('tool')",
            "dynamic import",
        ),
    ],
)
def test_architecture_negative_fixtures(path, source, rule):
    assert any(rule in violation for violation in inspect_sources({path: source}))


def test_composition_and_own_slice_are_allowed():
    handler_path = "agentgate/features/request_operation/handler.py"
    assert (
        inspect_sources(
            {
                "agentgate/dependencies.py": "from agentgate.infrastructure import persistence",
                handler_path: "from .command import RequestOperationCommand",
            }
        )
        == []
    )


def test_dependency_cycle_is_rejected():
    result = inspect_sources(
        {
            "agentgate/domain/a.py": "from .b import value",
            "agentgate/domain/b.py": "from .a import value",
        }
    )
    assert any("cycle" in violation for violation in result)


@pytest.mark.parametrize(
    "path,source,expected",
    [
        (
            "agentgate/domain/value_objects/role.py",
            "from enum import StrEnum as E\nclass Role(E): AGENT = 'AGENT'",
            "domain enums belong",
        ),
        (
            "agentgate/domain/enums/principal.py",
            "class Principal: pass",
            "only enum types",
        ),
    ],
)
def test_domain_enum_classification_rejects_wrong_ownership(path, source, expected):
    assert any(expected in issue for issue in inspect_organization({path: source}))


def test_domain_enum_classification_accepts_canonical_enum():
    assert (
        inspect_organization(
            {
                "agentgate/domain/enums/role.py": (
                    "from enum import StrEnum\nclass Role(StrEnum): AGENT = 'AGENT'"
                )
            }
        )
        == []
    )
