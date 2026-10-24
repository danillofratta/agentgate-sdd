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


def resolved_imports(path, tree):
    """Resolve names consistently for normal, aliased, relative, and type-only imports."""
    module = module_name(path)
    package = module if path.endswith("__init__.py") else module.rpartition(".")[0]
    imports, aliases = [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                binding = alias.asname or alias.name.split(".")[0]
                aliases[binding] = alias.name if alias.asname else binding
        elif isinstance(node, ast.ImportFrom):
            target = node.module or ""
            if node.level:
                target = importlib.util.resolve_name("." * node.level + target, package)
            imports.append(target)
            for alias in node.names:
                imports.append(target + "." + alias.name)
                aliases[alias.asname or alias.name] = target + "." + alias.name
    return imports, aliases


def qualified_name(node, aliases):
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return qualified_name(node.value, aliases) + "." + node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            expression = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return ""
        return qualified_name(expression, aliases)
    return ""


def inspect_sources(sources):
    """Check inward imports, feature isolation, and effect/dispatch boundaries."""
    violations = []
    graph = {module_name(path): set() for path in sources}
    for path, source in sources.items():
        module = module_name(path)
        tree = ast.parse(source)
        imports, aliases = resolved_imports(path, tree)

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
                if (
                    project
                    and not (target == "agentgate.domain" or target.startswith("agentgate.domain."))
                ) or (not project and root not in sys.stdlib_module_names and root != "__future__"):
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
                if project and not any(
                    target == item or target.startswith(item + ".") for item in allowed
                ):
                    reject("inward application imports")
                if not project and root not in sys.stdlib_module_names and root != "__future__":
                    reject("framework-free application")
                if root in {"sqlite3", "os", "socket", "subprocess", "importlib"}:
                    reject("concrete application dependency")
                if target.startswith("agentgate.features") and not in_feature:
                    reject("ports cannot depend on features")
                if in_feature and target.endswith((".models", ".endpoint")):
                    reject("handler/core imports HTTP adapter")
                if (
                    in_feature
                    and target.startswith("agentgate.features.")
                    and (
                        "handler" in target.split(".")
                        or ".handler." in target
                        or target.endswith(".handler")
                        or target.split(".")[-1].endswith("Handler")
                    )
                ):
                    reject("direct feature handler dependency")
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
            return qualified_name(node, names)

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
    violations.extend(inspect_cqrs(sources))
    violations.extend(inspect_injection(sources))
    return violations


def inspect_cqrs(sources):
    """Check explicit request roles and common persistent effects in query handlers.

    Static guards cover declared imports and calls; behavior tests remain necessary
    for effects hidden behind arbitrary implementations of an injected port.
    """
    violations = []
    modules = {module_name(path): ast.parse(source) for path, source in sources.items()}
    for path in sources:
        module = module_name(path)
        parts = module.split(".")
        if len(parts) != 4 or parts[:2] != ["agentgate", "features"]:
            continue
        feature = ".".join(parts[:3])
        role = parts[-1]
        tree = modules[module]
        imports, aliases = resolved_imports(path, tree)
        requests = [name for name in ("command", "query") if feature + "." + name in modules]
        if role in {"command", "query", "handler"} and len(requests) > 1:
            violations.append(f"{path}: CQRS feature mixes command and query requests")
        if role in {"command", "query"}:
            suffix = role.title()
            classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
            if len(classes) != 1 or not classes[0].name.endswith(suffix):
                violations.append(f"{path}: CQRS {role} module requires one {suffix} request")
            if any(
                target == feature + "." + other or target.startswith(feature + "." + other + ".")
                for target in imports
                for other in {"command", "query"} - {role}
            ):
                violations.append(f"{path}: CQRS request depends on opposite request role")
            for node in classes:
                if any(
                    isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                    and item.name in {"handle", "execute", "evaluate"}
                    for item in node.body
                ):
                    violations.append(f"{path}: CQRS requests carry data, not handlers")
        if role != "handler":
            continue
        for handler in (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Handler")
        ):
            if len(requests) != 1:
                violations.append(f"{path}: CQRS handler requires exactly one request module")
                continue
            request_role = requests[0]
            handle = next(
                (
                    item
                    for item in handler.body
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                    and item.name == "handle"
                ),
                None,
            )
            expected_prefix = feature + "." + request_role + "."
            if handle is None:
                violations.append(f"{path}: CQRS handler requires an explicit handle method")
                continue
            annotations = [
                qualified_name(arg.annotation, aliases)
                for arg in handle.args.posonlyargs + handle.args.args + handle.args.kwonlyargs
                if arg.arg not in {"self", "cls"}
            ]
            if sum(
                name.startswith(expected_prefix) and name.endswith(request_role.title())
                for name in annotations
            ) != 1 or any(
                name.endswith("Command" if request_role == "query" else "Query")
                for name in annotations
            ):
                violations.append(
                    f"{path}: CQRS handler must accept its own {request_role} request"
                )
            if request_role != "query":
                continue
            for method in (
                item
                for item in handler.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                and item.name != "__init__"
            ):
                for node in ast.walk(method):
                    if isinstance(node, ast.Call):
                        name = qualified_name(node.func, aliases)
                        action = name.rsplit(".", 1)[-1]
                        receiver = name.rpartition(".")[0].lower()
                        state_port = any(
                            part in receiver
                            for part in (
                                "repo",
                                "audit",
                                "work",
                                "session",
                                "store",
                                "writer",
                                "gateway",
                            )
                        )
                        if action in {
                            "commit",
                            "consume",
                            "approve",
                            "reject",
                            "publish",
                            "publish_event",
                            "execute_tool",
                            "invoke_tool",
                            "dispatch",
                        } or (
                            state_port and action in {"add", "append", "save", "update", "delete"}
                        ):
                            violations.append(
                                f"{path}: CQRS query handler performs a write/dispatch"
                            )
                    if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            name = qualified_name(target, aliases)
                            if isinstance(target, ast.Subscript):
                                name = qualified_name(target.value, aliases)
                            if name.startswith(("self.", "query.")):
                                violations.append(f"{path}: CQRS query handler mutates state")
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
        _, aliases = resolved_imports(path, tree)
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
            bases = {
                qualified_name(
                    base.value if isinstance(base, ast.Subscript) else base, aliases
                ).rsplit(".", 1)[-1]
                for base in node.bases
            }
            contract = bool(bases & {"Protocol", "ABC"})
            domain_repository = parts[1:3] == ("domain", "repositories")
            application_port = parts[1:3] == ("application", "ports")
            adapter_kind = parts[1:3]
            if (
                contract
                and node.name.endswith(("Gateway", "EventPublisher"))
                and not application_port
            ):
                violations.append(
                    f"{path}: gateway/publisher contracts belong in application/ports"
                )
            if adapter_kind == ("infrastructure", "gateways") and not node.name.endswith("Gateway"):
                violations.append(f"{path}: gateway adapter requires Gateway suffix")
            if node.name.endswith("Gateway") and "infrastructure" in parts:
                if adapter_kind != ("infrastructure", "gateways"):
                    violations.append(f"{path}: gateway adapters belong in infrastructure/gateways")
            if node.name.endswith("Repository") and "infrastructure" in parts:
                if adapter_kind != ("infrastructure", "repositories"):
                    violations.append(
                        f"{path}: repository adapters belong in infrastructure/repositories"
                    )
            if "infrastructure" in parts and (
                re.match(r"I[A-Z]", node.name) or node.name.startswith("Base")
            ):
                violations.append(f"{path}: generic adapter name")
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


def inspect_injection(sources):
    """Reject hidden collaborators; resolve constructor annotations against inward ports."""
    violations = []
    contracts = set()
    for path, source in sources.items():
        if not path.startswith(("agentgate/application/ports/", "agentgate/domain/repositories/")):
            continue
        tree = ast.parse(source)
        _, aliases = resolved_imports(path, tree)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                qualified_name(
                    base.value if isinstance(base, ast.Subscript) else base, aliases
                ).rsplit(".", 1)[-1]
                in {"Protocol", "ABC"}
                for base in node.bases
            ):
                contracts.add(module_name(path) + "." + node.name)
    for path, source in sources.items():
        parts = PurePosixPath(path).parts
        core = parts[1:2] == ("application",) or (
            parts[1:2] == ("features",) and PurePosixPath(path).stem not in {"endpoint", "models"}
        )
        if not core:
            continue
        tree = ast.parse(source)
        _, aliases = resolved_imports(path, tree)
        for node in tree.body:
            if isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [qualified_name(target, aliases).lower().strip("_") for target in targets]
                value = node.value
                if any(
                    name in {"container", "services", "service_locator", "registry"}
                    for name in names
                ):
                    violations.append(f"{path}: hidden dependency in module-level container")
                if isinstance(value, ast.Call) and qualified_name(value.func, aliases).rsplit(
                    ".", 1
                )[-1] in {"dict", "list", "set", "defaultdict", "SimpleNamespace"}:
                    violations.append(f"{path}: hidden dependency in mutable module-level state")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = qualified_name(node.func, aliases)
            leaf = name.rsplit(".", 1)[-1]
            receiver = name.rpartition(".")[0].lower()
            if leaf in {
                "get_components",
                "build_components",
                "get_repository",
                "build_repository",
                "get_gateway",
                "create_gateway",
                "get_instance",
            } or (
                leaf == "get"
                and any(term in receiver for term in ("container", "locator", "services"))
            ):
                violations.append(f"{path}: hidden dependency resolution")
            if (
                name.startswith("agentgate.infrastructure.")
                or name in contracts
                or (
                    leaf[:1].isupper()
                    and leaf.endswith(("Repository", "Gateway", "Handler", "UnitOfWork"))
                )
            ):
                violations.append(f"{path}: collaborator constructed outside composition root")
        if PurePosixPath(path).stem != "handler":
            continue
        for handler in (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Handler")
        ):
            constructor = next(
                (
                    node
                    for node in handler.body
                    if isinstance(node, ast.FunctionDef) and node.name == "__init__"
                ),
                None,
            )
            if constructor is None:
                continue  # A pure, dependency-free handler needs no constructor ceremony.
            parameters = constructor.args.posonlyargs + constructor.args.args
            defaults = [None] * (
                len(parameters) - len(constructor.args.defaults)
            ) + constructor.args.defaults
            pairs = list(zip(parameters, defaults, strict=True)) + list(
                zip(constructor.args.kwonlyargs, constructor.args.kw_defaults, strict=True)
            )
            for parameter, default in pairs:
                if parameter.arg == "self":
                    continue
                annotation = parameter.annotation
                if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
                    annotation = ast.parse(annotation.value, mode="eval").body
                symbols = (
                    {
                        qualified_name(node, aliases)
                        for node in ast.walk(annotation)
                        if isinstance(node, ast.Name | ast.Attribute)
                    }
                    if annotation
                    else set()
                )
                inward_port = bool(symbols & contracts)
                data_value = symbols and all(
                    name in {"str", "int", "bool", "float", "bytes", "None"}
                    or name.startswith("agentgate.domain.value_objects.")
                    for name in symbols
                )
                if not inward_port and not data_value:
                    violations.append(
                        f"{path}: constructor collaborators must use inward port contracts"
                    )
                if (
                    inward_port
                    and default is not None
                    and not (isinstance(default, ast.Constant) and default.value is None)
                ):
                    violations.append(f"{path}: constructor collaborator has a hidden default")
            if constructor.args.vararg or constructor.args.kwarg:
                violations.append(f"{path}: constructor dependencies must be explicit")
    return violations
