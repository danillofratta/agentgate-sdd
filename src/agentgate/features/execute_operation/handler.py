from agentgate.application.exceptions.commit_uncertain import CommitUncertain
from agentgate.application.exceptions.execution_timed_out import ExecutionTimedOut
from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.exceptions.not_found import NotFound
from agentgate.application.exceptions.storage_unavailable import StorageUnavailable
from agentgate.application.exceptions.transient_storage_lock import TransientStorageLock
from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluatorGateway
from agentgate.application.ports.principal_gateway import PrincipalGateway
from agentgate.application.ports.request_unit_of_work import RequestUnitOfWork
from agentgate.application.ports.request_unit_of_work_factory import RequestUnitOfWorkFactory
from agentgate.application.ports.sleeper_gateway import SleeperGateway
from agentgate.application.ports.tool_registry_gateway import ToolRegistryGateway
from agentgate.domain.entities.operation import Operation
from agentgate.domain.events.operation_failed_event import OperationFailedEvent
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.approval_state import ApprovalState
from agentgate.domain.value_objects.decision import Decision
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
        recovery_unit_of_work: RequestUnitOfWorkFactory | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._recovery_work = recovery_unit_of_work or unit_of_work
        self._clock = clock
        self._principals = principals
        self._harness = Harness(tools, policy, clock, sleeper)

    def handle(self, command: ExecuteOperationCommand) -> ExecuteOperationResult:
        if command.principal.role != Role.AGENT:
            raise Forbidden
        deadline = self._harness.start_deadline()
        try:
            for attempt in range(2):
                try:
                    deadline.remaining()
                except ExecutionTimedOut as error:
                    # No transaction has started, or the previous attempt rolled back.
                    error.rollback_confirmed = True
                    raise
                replay = self._record_attempt(command, deadline)
                if replay is not None:
                    return replay
                try:
                    return self._attempt(command, deadline)
                except CommitUncertain:
                    return self._reconcile(command)
                except TransientStorageLock:
                    if attempt == 1:
                        raise
                    try:
                        self._harness.retry_delay(deadline)
                        deadline.remaining()
                    except ExecutionTimedOut as error:
                        error.rollback_confirmed = True
                        raise
        except (ExecutionUnavailable, StorageUnavailable) as error:
            if isinstance(error, CommitUncertain):
                raise StorageUnavailable from None
            if error.rollback_confirmed:
                replay = self._record_failure(command, error)
                if replay is not None:
                    return replay
            raise
        raise AssertionError("unreachable")

    def terminal_result(self, command: ExecuteOperationCommand) -> ExecuteOperationResult:
        """Return only confirmed durable terminal failure evidence to an inbound adapter."""
        if command.principal.role != Role.AGENT:
            raise Forbidden
        deadline = ExecutionDeadline(self._clock, self._clock.monotonic() + 0.05)
        with self._transaction(self._recovery_work, deadline) as work:
            operation = self._load(work, command)
            self._principal(command)
            if operation.state not in {OperationState.FAILED, OperationState.TIMED_OUT}:
                raise StorageUnavailable
            return ExecuteOperationResult(operation, None)

    def _load(self, work: RequestUnitOfWork, command: ExecuteOperationCommand) -> Operation:
        operation = work.operations.get(command.operation_id)
        if (
            not isinstance(operation, Operation)
            or operation.id != command.operation_id
            or operation.principal_id != command.principal.id
        ):
            raise NotFound
        return operation

    def _transaction(
        self, factory: RequestUnitOfWorkFactory, deadline: ExecutionDeadline
    ) -> RequestUnitOfWork:
        try:
            transaction = factory()
            transaction.set_deadline(deadline)
            return transaction
        except Exception:
            raise StorageUnavailable from None

    def _principal(self, command: ExecuteOperationCommand) -> Principal:
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
        return current

    def _replay(
        self, work: RequestUnitOfWork, operation: Operation
    ) -> ExecuteOperationResult | None:
        if operation.state == OperationState.SUCCEEDED:
            stored = work.operations.get_result(operation.id)
            if stored is None:
                raise StorageUnavailable
            if operation.policy.decision == Decision.REQUIRE_APPROVAL:
                approval = work.approvals.get(operation.id)
                if approval is None or approval.state != ApprovalState.CONSUMED:
                    raise StorageUnavailable
            return ExecuteOperationResult(operation, stored)
        if operation.state == OperationState.TIMED_OUT:
            raise ExecutionTimedOut
        if operation.state == OperationState.FAILED:
            raise ExecutionUnavailable
        return None

    def _record_attempt(
        self, command: ExecuteOperationCommand, deadline: ExecutionDeadline
    ) -> ExecuteOperationResult | None:
        transaction = self._transaction(self._recovery_work, deadline)
        ready = False
        try:
            with transaction as work:
                operation = self._load(work, command)
                current = self._principal(command)
                replay = self._replay(work, operation)
                if replay is not None:
                    return replay
                if (
                    work.operations.get_result(operation.id) is not None
                    or operation.execution_authorization is not None
                ):
                    raise StorageUnavailable
                ready = True
                self._harness.prepare(work, operation, current, deadline)
                work.audit.append_attempt(operation, self._clock.now())
                work.commit()
        except ExecutionTimedOut as error:
            error.rollback_confirmed = ready and transaction.rollback_confirmed
            raise
        except (ExecutionUnavailable, StorageUnavailable):
            raise
        except (Forbidden, NotFound):
            raise
        except Exception as error:
            if isinstance(error, InvariantViolation):
                raise
            raise StorageUnavailable from None
        return None

    def _reconcile(self, command: ExecuteOperationCommand) -> ExecuteOperationResult:
        transaction = self._transaction(
            self._recovery_work, ExecutionDeadline(self._clock, self._clock.monotonic() + 0.05)
        )
        try:
            with transaction as work:
                operation = self._load(work, command)
                self._principal(command)
                work.accounts.facts()
                replay = self._replay(work, operation)
                if replay is not None:
                    return replay
                # READY plus absent result and unconsumed approval is authoritative
                # no-effect evidence in this single atomic database. Do not redispatch
                # within the call whose commit confirmation failed.
                if (
                    operation.state != OperationState.READY
                    or work.operations.get_result(operation.id) is not None
                ):
                    raise StorageUnavailable
                if operation.execution_authorization is not None:
                    raise StorageUnavailable
                if operation.policy.decision == Decision.REQUIRE_APPROVAL:
                    approval = work.approvals.get(operation.id)
                    if approval is None or approval.state != ApprovalState.GRANTED:
                        raise StorageUnavailable
        except Exception:
            raise StorageUnavailable from None
        raise StorageUnavailable

    def _record_failure(
        self, command: ExecuteOperationCommand, error: Exception
    ) -> ExecuteOperationResult | None:
        transaction = self._transaction(
            self._recovery_work, ExecutionDeadline(self._clock, self._clock.monotonic() + 0.05)
        )
        try:
            with transaction as work:
                operation = self._load(work, command)
                replay = self._replay(work, operation)
                if replay is not None:
                    return replay
                if operation.state != OperationState.READY:
                    raise StorageUnavailable
                state = (
                    OperationState.TIMED_OUT
                    if isinstance(error, ExecutionTimedOut)
                    else OperationState.FAILED
                )
                failed = operation.transition(state)
                work.operations.save_failure(failed)
                work.audit.append(
                    OperationFailedEvent(
                        failed.id,
                        failed.principal_id,
                        failed.request.tool,
                        failed.request.fingerprint,
                        failed.policy.version,
                        self._clock.now(),
                        state,
                    )
                )
                work.commit()
        except Exception:
            # A terminal-write failure must never claim durable terminal state.
            raise StorageUnavailable from None
        return None

    def _attempt(
        self, command: ExecuteOperationCommand, deadline: ExecutionDeadline
    ) -> ExecuteOperationResult:
        transaction = self._transaction(self._unit_of_work, deadline)
        try:
            with transaction as work:
                operation = self._load(work, command)
                current = self._principal(command)
                replay = self._replay(work, operation)
                if replay is not None:
                    return replay
                result = self._harness.run(work, operation, current, deadline)
                deadline.remaining()
                work.commit()
                return result
        except (CommitUncertain, Forbidden, NotFound):
            raise
        except Exception as error:
            if isinstance(error, InvalidTransition):
                raise
            if not transaction.rollback_confirmed:
                raise StorageUnavailable from None
            safe = (
                error
                if isinstance(
                    error, (ExecutionUnavailable, StorageUnavailable, TransientStorageLock)
                )
                else ExecutionUnavailable()
            )
            safe.rollback_confirmed = True
            raise safe from None
