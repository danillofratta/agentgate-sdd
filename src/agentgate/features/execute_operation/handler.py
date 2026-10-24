from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluatorGateway
from agentgate.application.ports.request_unit_of_work_factory import RequestUnitOfWorkFactory
from agentgate.application.ports.sleeper_gateway import SleeperGateway
from agentgate.application.ports.tool_registry_gateway import ToolRegistryGateway
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
    ) -> None:
        self._unit_of_work = unit_of_work
        self._harness = Harness(tools, policy, clock, sleeper)

    def handle(self, command: ExecuteOperationCommand) -> ExecuteOperationResult:
        if command.principal.role != Role.AGENT:
            raise Forbidden
        with self._unit_of_work() as work:
            operation = work.operations.get(command.operation_id)
            if (
                operation is None
                or operation.id != command.operation_id
                or operation.principal_id != command.principal.id
            ):
                raise NotFound
            result = self._harness.run(work, operation, command.principal)
            work.commit()
            return result
