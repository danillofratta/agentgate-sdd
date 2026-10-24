from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluatorGateway
from agentgate.application.ports.principal_gateway import PrincipalGateway
from agentgate.application.ports.request_unit_of_work_factory import RequestUnitOfWorkFactory
from agentgate.application.ports.sleeper_gateway import SleeperGateway
from agentgate.application.ports.tool_registry_gateway import ToolRegistryGateway
from agentgate.domain.entities.operation import Operation
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.role import Role
from agentgate.features.execute_operation.command import ExecuteOperationCommand
from agentgate.features.execute_operation.harness import Harness
from agentgate.features.execute_operation.result import ExecuteOperationResult


class ExecuteOperationHandler:
    def __init__(
        self,
        unit_of_work: RequestUnitOfWorkFactory,
        tools: ToolRegistryGateway,
        policy: PolicyEvaluatorGateway,
        clock: ClockGateway,
        sleeper: SleeperGateway,
        principals: PrincipalGateway,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._principals = principals
        self._harness = Harness(tools, policy, clock, sleeper)

    def handle(self, command: ExecuteOperationCommand) -> ExecuteOperationResult:
        if command.principal.role != Role.AGENT:
            raise Forbidden
        with self._unit_of_work() as work:
            operation = work.operations.get(command.operation_id)
            if (
                not isinstance(operation, Operation)
                or operation.id != command.operation_id
                or operation.principal_id != command.principal.id
            ):
                raise NotFound
            try:
                current = self._principals.get_principal(command.principal.id)
            except Exception:
                raise Forbidden from None
            if (
                not isinstance(current, Principal)
                or current.id != command.principal.id
                or current.role != Role.AGENT
            ):
                raise Forbidden
            if operation.state == OperationState.SUCCEEDED:
                stored = work.operations.get_result(operation.id)
                if stored is None:
                    raise ExecutionUnavailable
                return ExecuteOperationResult(operation, stored)
            result = self._harness.run(work, operation, current)
            work.commit()
            return result
