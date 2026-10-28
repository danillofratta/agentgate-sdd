from agentgate.application.exceptions.execution_conflict import ExecutionConflict
from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.execution_deadline import ExecutionDeadline
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluatorGateway
from agentgate.application.ports.request_unit_of_work import RequestUnitOfWork
from agentgate.application.ports.sleeper_gateway import SleeperGateway
from agentgate.application.ports.tool_registry_gateway import ToolRegistryGateway
from agentgate.domain.entities.account import Account
from agentgate.domain.entities.approval import Approval
from agentgate.domain.entities.operation import Operation
from agentgate.domain.enums.decision import Decision
from agentgate.domain.enums.operation_state import OperationState
from agentgate.domain.enums.reason import Reason
from agentgate.domain.enums.tool import Tool
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.policies.operation_policy import CURRENT_POLICY_VERSION
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.transfer_arguments import TransferArguments
from agentgate.features.execute_operation.result import ExecuteOperationResult


class Harness:
    """One authorized synchronous local dispatch inside the caller's write transaction."""

    def __init__(
        self,
        tools: ToolRegistryGateway,
        policy: PolicyEvaluatorGateway,
        clock: ClockGateway,
        sleeper: SleeperGateway,
    ) -> None:
        self._tools = tools
        self._policy = policy
        self._clock = clock
        self._sleeper = sleeper

    def start_deadline(self) -> ExecutionDeadline:
        return ExecutionDeadline(self._clock, self._clock.monotonic() + 2.0)

    def retry_delay(self, deadline: ExecutionDeadline) -> None:
        self._sleeper.sleep(min(0.05, deadline.remaining()))

    def prepare(
        self,
        work: RequestUnitOfWork,
        operation: Operation,
        principal: Principal,
        deadline: ExecutionDeadline,
    ) -> tuple[tuple[AccountFacts, ...], Approval | None, Operation]:
        if operation.request.tool not in (Tool.GET_BALANCE, Tool.SIMULATE_TRANSFER):
            raise Forbidden
        if operation.state == OperationState.DENIED:
            raise Forbidden
        if operation.state != OperationState.READY:
            raise ExecutionConflict("OPERATION_NOT_READY")
        if (
            operation.policy.decision not in (Decision.ALLOW, Decision.REQUIRE_APPROVAL)
            or operation.policy.version != CURRENT_POLICY_VERSION
            or operation.request.tool not in principal.tools
            or operation.request.source not in principal.source_accounts
        ):
            raise Forbidden
        accounts = work.accounts.facts()
        try:
            if (
                not isinstance(accounts, tuple)
                or any(type(account) is not AccountFacts for account in accounts)
                or len({account.id for account in accounts}) != len(accounts)
                or operation.request.source not in {account.id for account in accounts}
            ):
                raise Forbidden
            policy = self._policy.evaluate(PolicySnapshot(principal, operation.request, accounts))
            if (
                not isinstance(policy, PolicyDecision)
                or policy.decision == Decision.DENY
                or policy.version != CURRENT_POLICY_VERSION
                or policy.decision != operation.policy.decision
            ):
                raise Forbidden
        except Exception:
            raise Forbidden from None
        args = operation.request.arguments
        if not isinstance(args, (BalanceArguments, TransferArguments)):
            raise Forbidden
        consumed = None
        if operation.policy.decision == Decision.REQUIRE_APPROVAL:
            approval = work.approvals.get(operation.id)
            if approval is None:
                raise ExecutionConflict("APPROVAL_REQUIRED")
            consumed = approval.consume(
                operation, policy.version, self._clock.now(), principal=principal
            )
        authorization = PolicyDecision(
            Decision.ALLOW,
            Reason.HUMAN_APPROVED if consumed is not None else Reason.PERMITTED,
            policy.version,
        )
        authorized = operation.authorize_execution(authorization)
        return accounts, consumed, authorized

    def run(
        self,
        work: RequestUnitOfWork,
        operation: Operation,
        principal: Principal,
        deadline: ExecutionDeadline,
    ) -> ExecuteOperationResult:
        accounts, consumed, authorized = self.prepare(work, operation, principal, deadline)
        args = operation.request.arguments
        deadline.remaining()
        work.audit.append(
            OperationDispatchedEvent(
                operation.id,
                operation.principal_id,
                operation.request.tool,
                operation.request.fingerprint,
                operation.policy.version,
                self._clock.now(),
            )
        )
        deadline.remaining()
        try:
            result = self._tools.dispatch(operation.request.tool, args, accounts)
        except Exception:
            raise ExecutionUnavailable from None
        if isinstance(args, BalanceArguments):
            if type(result) is not BalanceResult or result.account_id != args.account_id:
                raise ExecutionUnavailable
        else:
            if type(result) is not TransferArguments or result != args:
                raise ExecutionUnavailable
            entities = {fact.id: Account(fact.id, fact.balance_cents) for fact in accounts}
            source, destination = entities[args.source_account_id].transfer_to(
                entities[args.destination_account_id], args.amount
            )
            deadline.remaining()
            work.accounts.save(source)
            deadline.remaining()
            work.accounts.save(destination)
        completed = authorized.transition(OperationState.SUCCEEDED)
        deadline.remaining()
        work.operations.save_execution(completed, result)
        if consumed is not None:
            deadline.remaining()
            work.approvals.save_consumption(consumed)
        deadline.remaining()
        work.audit.append(completed.executed_event(self._clock.now()))
        return ExecuteOperationResult(completed, result)
