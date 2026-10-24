from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.idempotency_conflict import IdempotencyConflict
from agentgate.application.ports.clock_gateway import Clock
from agentgate.application.ports.operation_id_generator_gateway import OperationIdGenerator
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluator
from agentgate.application.ports.request_unit_of_work_factory_gateway import RequestUnitOfWorkFactory
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.events.operation_requested import OperationRequested
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_id import OperationId
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
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
        policy: PolicyEvaluator,
        clock: Clock,
        ids: OperationIdGenerator,
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
                return RequestOperationResult(existing, created=False)
            try:
                snapshot = PolicySnapshot(command.principal, command.request, work.accounts.facts())
                policy = self._policy.evaluate(snapshot)
                if not isinstance(policy, PolicyDecision) or policy.version != PolicyVersion("v1"):
                    raise ValueError("UNSUPPORTED_POLICY")
            except Exception:
                # Uncertain authorization must deny without exposing exception details.
                policy = PolicyDecision(Decision.DENY, Reason.POLICY_UNCERTAIN, PolicyVersion("v1"))
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
            work.audit.append(
                OperationRequested(
                    operation.id,
                    operation.principal_id,
                    operation.request.tool,
                    policy,
                    operation.created_at,
                )
            )
            work.commit()
            return RequestOperationResult(operation, created=True)
