import ast
import importlib.util
import re
import sys
from pathlib import PurePosixPath


def module_name(path):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def inspect_sources(sources):
    """Check inward imports, feature isolation, and effect/dispatch boundaries."""
    violations = []
    graph = {module_name(path): set() for path in sources}
    for path, source in sources.items():
        module = module_name(path)
        package = module if path.endswith("__init__.py") else module.rpartition(".")[0]
        tree = ast.parse(source)
        imports, aliases = [], {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if node.level:
                    target = importlib.util.resolve_name("." * node.level + target, package)
                imports.append(target)
                for alias in node.names:
                    imports.append(target + "." + alias.name)
                    aliases[alias.asname or alias.name] = target + "." + alias.name

        def reject(rule, source_path=path):
            violations.append(f"{source_path}: {rule}")

        in_feature = module.startswith("agentgate.features.")
        is_http = in_feature and PurePosixPath(path).stem in {"endpoint", "models"}
        core = module.startswith("agentgate.application") or (in_feature and not is_http)
        for target in imports:
            root = target.split(".")[0]
            project = target == "agentgate" or target.startswith("agentgate.")
            candidates = [name for name in graph if target == name or target.startswith(name + ".")]
            if candidates:
                dependency = max(candidates, key=len)
                if dependency != module:
                    graph[module].add(dependency)
            if module.startswith("agentgate.domain"):
                if (project and not target.startswith("agentgate.domain")) or (
                    not project and root not in sys.stdlib_module_names and root != "__future__"
                ):
                    reject("domain purity")
                if root in {
                    "os",
                    "sys",
                    "io",
                    "pathlib",
                    "socket",
                    "subprocess",
                    "sqlite3",
                    "random",
                    "secrets",
                    "time",
                    "importlib",
                }:
                    reject("domain I/O")
            if core:
                allowed = ("agentgate.domain", "agentgate.application")
                if in_feature:
                    own_slice = ".".join(module.split(".")[:3])
                    allowed += (own_slice,)
                if project and not target.startswith(allowed):
                    reject("inward application imports")
                if not project and root not in sys.stdlib_module_names and root != "__future__":
                    reject("framework-free application")
                if root in {"sqlite3", "os", "socket", "subprocess", "importlib"}:
                    reject("concrete application dependency")
                if target.startswith("agentgate.features") and not in_feature:
                    reject("ports cannot depend on features")
                if in_feature and target.endswith((".models", ".endpoint")):
                    reject("handler/core imports HTTP adapter")
            if in_feature and target.startswith("agentgate.features."):
                if module.split(".")[2] != target.split(".")[2]:
                    reject("sibling slice import")
            if module.startswith("agentgate.infrastructure") and target.startswith(
                (
                    "agentgate.features",
                    "agentgate.transport",
                    "agentgate.api",
                    "agentgate.main",
                    "agentgate.dependencies",
                    "agentgate.components",
                )
            ):
                reject("adapter depends outward")
            if (
                in_feature
                or module.startswith("agentgate.transport")
                or module in {"agentgate.main", "agentgate.components"}
            ):
                if target.startswith("agentgate.infrastructure") or root == "sqlite3":
                    reject("concrete dependency outside composition")
            if module == "agentgate" and project:
                reject("root re-export escape")
            if root == "importlib":
                reject("dynamic import")

        def call_name(node, names=aliases):
            if isinstance(node, ast.Name):
                return names.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return call_name(node.value, names) + "." + node.attr
            return ""

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = call_name(node.func).rsplit(".", 1)[-1]
            if method in {"eval", "exec", "__import__", "import_module"}:
                reject("dynamic execution")
            if module.startswith("agentgate.domain") and method in {
                "open",
                "read_text",
                "write_text",
                "now",
                "utcnow",
                "today",
                "uuid4",
            }:
                reject("domain I/O or clock")
            if not module.startswith("agentgate.infrastructure") and method in {
                "execute",
                "executemany",
                "executescript",
            }:
                reject("SQL outside adapter")
            if method in {"dispatch", "execute_tool", "invoke_tool"} and module != (
                "agentgate.features.execute_operation.harness"
            ):
                reject("tool dispatch outside harness")
            if core and method in {"Depends", "resolve", "get_service", "get_dependency"}:
                reject("hidden dependency resolution")
        if core:
            for node in tree.body:
                if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(
                    node.value, ast.Dict | ast.List | ast.Set
                ):
                    reject("mutable application global")

    visited, active = set(), set()

    def visit(module):
        if module in active:
            violations.append(f"{module}: dependency cycle")
            return
        if module in visited:
            return
        active.add(module)
        for dependency in graph[module]:
            visit(dependency)
        active.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)
    return violations


def inspect_organization(sources):
    """Check feature-local endpoints, domain-owned repositories, and file naming."""
    violations = []
    technical_ports = {
        "Clock",
        "PolicyEvaluator",
        "OperationIdGenerator",
        "RequestUnitOfWork",
        "RequestUnitOfWorkFactory",
    }
    cqrs_names = {"Command": "command", "Query": "query", "Handler": "handler", "Result": "result"}
    endpoint_methods = {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "options",
        "head",
        "api_route",
        "websocket",
        "route",
    }
    for path, source in sources.items():
        tree = ast.parse(source)
        parts = PurePosixPath(path).parts
        stem = PurePosixPath(path).stem
        feature = len(parts) >= 4 and parts[1] == "features"
        schema_module = feature and stem == "models"
        endpoint_module = feature and stem == "endpoint"
        if parts[1:2] == ("api",) or "controllers" in parts or "routes" in parts:
            violations.append(f"{path}: centralized endpoint directory is forbidden")
        if parts[1:3] == ("application", "features"):
            violations.append(f"{path}: features must live under agentgate/features")
        if stem in {"entities", "services", "ports"} or (stem == "models" and not schema_module):
            violations.append(f"{path}: grouped generic module")
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        known_schemas = {"BaseModel"}
        if not schema_module and (
            len(classes) > 1 or any(node not in tree.body for node in classes)
        ):
            violations.append(f"{path}: one class per file")
        for node in classes:
            if schema_module:
                if not any(ast.unparse(base) in known_schemas for base in node.bases):
                    violations.append(f"{path}: models.py may group only HTTP schemas")
                known_schemas.add(node.name)
            name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", node.name)
            expected = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
            if feature and not schema_module:
                expected = next(
                    (
                        filename
                        for suffix, filename in cqrs_names.items()
                        if node.name.endswith(suffix)
                    ),
                    expected,
                )
            if not schema_module and stem != expected:
                violations.append(f"{path}: class must use {expected}.py")
            bases = {ast.unparse(base).rsplit(".", 1)[-1] for base in node.bases}
            contract = bool(bases & {"Protocol", "ABC"})
            domain_repository = parts[1:3] == ("domain", "repositories")
            application_port = parts[1:3] == ("application", "ports")
            if (
                node.name.endswith("Repository")
                and not domain_repository
                and (contract or "infrastructure" not in parts)
            ):
                violations.append(f"{path}: repository contracts belong in domain/repositories")
            if domain_repository or application_port:
                if not contract:
                    violations.append(f"{path}: port must declare Protocol or ABC")
                if re.match(r"I[A-Z]", node.name) or node.name.startswith("Base"):
                    violations.append(f"{path}: generic port name")
                if node.name in technical_ports and application_port:
                    continue
                methods = {
                    item.name
                    for item in node.body
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                }
                suffix = None
                if methods & {"find", "add", "facts", "append", "save", "load"}:
                    suffix = "Repository"
                elif methods & {"publish", "publish_event"}:
                    suffix = "EventPublisher"
                elif methods & {"verify", "reconcile", "send_payment"}:
                    suffix = "Gateway"
                if domain_repository and not node.name.endswith("Repository"):
                    violations.append(f"{path}: domain persistence contracts require Repository")
                if suffix and not node.name.endswith(suffix):
                    violations.append(f"{path}: responsibility requires {suffix}")
                elif not node.name.endswith(("Repository", "Gateway", "EventPublisher")):
                    violations.append(f"{path}: port name must express responsibility")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "APIRouter" and not endpoint_module:
                    violations.append(f"{path}: routers belong in feature endpoint.py")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"add_api_route", "add_route", "add_websocket_route"}:
                    if not endpoint_module:
                        violations.append(f"{path}: endpoints belong in feature endpoint.py")
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in endpoint_methods
                    and not endpoint_module
                ):
                    violations.append(f"{path}: endpoints belong in feature endpoint.py")
        if stem == "endpoint" and not endpoint_module:
            violations.append(f"{path}: endpoints belong in feature endpoint.py")
    return violations
