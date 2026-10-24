from textwrap import indent

import pytest

from tests.architecture.rules import inspect_organization, inspect_sources


def feature_sources(role="command", body="return None", annotation=None):
    request = "Sample" + role.title()
    return {
        f"agentgate/features/sample/{role}.py": f"class {request}: pass",
        "agentgate/features/sample/handler.py": (
            f"from .{role} import {request}\n"
            "class SampleHandler:\n"
            f"    def handle(self, request: {annotation or request}):\n" + indent(body, "        ")
        ),
    }


@pytest.mark.parametrize("role", ["command", "query"])
def test_explicit_cqrs_requests_and_handlers_are_allowed(role):
    sources = feature_sources(role)
    assert inspect_sources(sources) == []
    assert inspect_organization(sources) == []


def test_forward_and_aliased_query_annotation_is_allowed():
    sources = feature_sources("query")
    sources["agentgate/features/sample/handler.py"] = (
        "from .query import SampleQuery as Q\n"
        "class SampleHandler:\n"
        "    def handle(self, query: 'Q'):\n"
        "        return query\n"
    )
    assert inspect_sources(sources) == []


def test_command_may_persist_and_query_may_build_local_results():
    assert inspect_sources(feature_sources("command", "self.repo.save(request)")) == []
    assert (
        inspect_sources(
            feature_sources("query", "results = []\nresults.append(request)\nreturn results")
        )
        == []
    )


def test_mixed_command_and_query_in_one_use_case_is_rejected():
    sources = feature_sources()
    sources["agentgate/features/sample/query.py"] = "class SampleQuery: pass"
    assert any("mixes command and query" in error for error in inspect_sources(sources))


@pytest.mark.parametrize("role,wrong", [("command", "SampleQuery"), ("query", "SampleCommand")])
def test_handler_cannot_accept_the_opposite_request_role(role, wrong):
    assert any(
        "must accept its own" in error
        for error in inspect_sources(feature_sources(role, annotation=wrong))
    )


@pytest.mark.parametrize("role", ["command", "query"])
def test_requests_cannot_implement_handler_behavior(role):
    sources = feature_sources(role)
    sources[f"agentgate/features/sample/{role}.py"] = (
        f"class Sample{role.title()}:\n    def execute(self): pass"
    )
    assert any("carry data" in error for error in inspect_sources(sources))


@pytest.mark.parametrize("signature", ["request", "request: object", "request: 'object'"])
def test_untyped_or_generic_request_handler_is_rejected(signature):
    sources = feature_sources()
    sources["agentgate/features/sample/handler.py"] = (
        f"class SampleHandler:\n    def handle(self, {signature}): pass"
    )
    assert any("must accept its own" in error for error in inspect_sources(sources))


def test_handler_without_an_explicit_request_module_is_rejected():
    handler = "class SampleHandler:\n    def handle(self, request): pass"
    sources = {"agentgate/features/sample/handler.py": handler}
    assert any("exactly one request module" in error for error in inspect_sources(sources))


@pytest.mark.parametrize(
    "write",
    [
        "self.repository.save(request)",
        "self.audit.append(request)",
        "self.work.commit()",
        "self.gateway.publish(request)",
        "self.tools.execute_tool(request)",
        "self.state = request",
        "self.state['balance'] = 0",
    ],
)
def test_query_writes_and_dispatch_are_rejected(write):
    assert any("CQRS query" in error for error in inspect_sources(feature_sources("query", write)))


@pytest.mark.parametrize(
    "dependency",
    [
        "from ..other.handler import OtherHandler",
        "from agentgate.features.other.handler import OtherHandler as H",
        "import agentgate.features.other.handler as handlers",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n from ..other.handler import OtherHandler",
        "from ..other import handler as other_handler",
    ],
)
def test_cross_slice_and_direct_handler_dependencies_are_rejected(dependency):
    sources = feature_sources()
    path = "agentgate/features/sample/handler.py"
    sources[path] = dependency + "\n" + sources[path]
    errors = inspect_sources(sources)
    assert any("sibling slice" in error for error in errors)
    assert any("direct feature handler" in error for error in errors)


def test_slice_prefix_cannot_be_used_to_import_a_neighbor():
    sources = feature_sources()
    sources["agentgate/features/sample/handler.py"] += (
        "\nfrom agentgate.features.sample_extra.command import ExtraCommand"
    )
    assert any("inward application imports" in error for error in inspect_sources(sources))


@pytest.mark.parametrize("location", ["command", "handler", "endpoint"])
def test_tool_dispatch_cannot_bypass_the_execution_harness(location):
    sources = {f"agentgate/features/sample/{location}.py": "tools.invoke_tool(request)"}
    assert any("dispatch outside harness" in error for error in inspect_sources(sources))
    assert (
        inspect_sources(
            {"agentgate/features/execute_operation/harness.py": "tools.invoke_tool(request)"}
        )
        == []
    )


@pytest.mark.parametrize(
    "path", ["agentgate/endpoint.py", "agentgate/controllers/sample.py", "agentgate/main.py"]
)
def test_endpoints_cannot_escape_their_feature(path):
    errors = inspect_organization({path: "@router.post('/operations')\ndef request(): pass"})
    assert any("endpoints belong" in error for error in errors)
