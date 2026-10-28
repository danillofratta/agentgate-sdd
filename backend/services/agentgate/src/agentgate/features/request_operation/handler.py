from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.idempotency_conflict import IdempotencyConflict
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.operation_id_generator_gateway import OperationIdGeneratorGateway
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluatorGateway
from agentgate.application.ports.request_unit_of_work_factory import (
    RequestUnitOfWorkFactory,
)
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.enums.role import Role
from agentgate.domain.policies.operation_policy import CURRENT_POLICY_VERSION
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.features.request_operation.command import (
    RequestOperationCommand,
)
from agentgate.features.request_operation.result import (
    RequestOperationResult,
)


class RequestOperationHandler:
    def __init__(
        self,
        unit_of_work: RequestUnitOfWorkFactory,
        policy: PolicyEvaluatorGateway,
        clock: ClockGateway,
        ids: OperationIdGeneratorGateway,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._policy = policy
        self._clock = clock
        self._ids = ids

    def handle(self, command: RequestOperationCommand) -> RequestOperationResult:
        if command.principal.role != Role.AGENT:
            raise Forbidden
        with self._unit_of_work() as work:
            existing = work.operations.find(command.principal.id, command.key)
            if existing is not None:
                if existing.request.fingerprint != command.request.fingerprint:
                    raise IdempotencyConflict
                return RequestOperationResult(
                    existing,
                    created=False,
                    result=work.operations.get_result(existing.id)
                    if existing.state == OperationState.SUCCEEDED
                    else None,
                )
            try:
                snapshot = PolicySnapshot(command.principal, command.request, work.accounts.facts())
                policy = self._policy.evaluate(snapshot)
                if (
                    not isinstance(policy, PolicyDecision)
                    or policy.version != CURRENT_POLICY_VERSION
                ):
                    raise ValueError("UNSUPPORTED_POLICY")
            except Exception:
                # Uncertain authorization must deny without exposing exception details.
                policy = PolicyDecision(
                    Decision.DENY, Reason.POLICY_UNCERTAIN, CURRENT_POLICY_VERSION
                )
            operation = Operation(
                OperationId(self._ids.next_id()),
                command.principal.id,
                command.key,
                command.request,
                policy,
                self._clock.now(),
            )
            work.operations.add(operation)
            if policy.decision == Decision.REQUIRE_APPROVAL:
                work.approvals.add(Approval(operation))
            work.audit.append(operation.requested_event())
            work.commit()
            return RequestOperationResult(operation, created=True)
