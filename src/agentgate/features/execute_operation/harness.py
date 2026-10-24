from agentgate.application.exceptions.execution_unavailable import ExecutionUnavailable
from agentgate.application.exceptions.forbidden import Forbidden
from agentgate.application.ports.clock_gateway import ClockGateway
from agentgate.application.ports.policy_evaluator_gateway import PolicyEvaluatorGateway
from agentgate.application.ports.request_unit_of_work import RequestUnitOfWork
from agentgate.application.ports.sleeper_gateway import SleeperGateway
from agentgate.application.ports.tool_registry_gateway import ToolRegistryGateway
from agentgate.domain.entities.operation import Operation
from agentgate.domain.events.operation_dispatched_event import OperationDispatchedEvent
from agentgate.domain.exceptions.invalid_transition import InvalidTransition
from agentgate.domain.policies.operation_policy import CURRENT_POLICY_VERSION
from agentgate.domain.value_objects.account_facts import AccountFacts
from agentgate.domain.value_objects.balance_arguments import BalanceArguments
from agentgate.domain.value_objects.balance_result import BalanceResult
from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.operation_state import OperationState
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.tool import Tool
from agentgate.features.execute_operation.result import ExecuteOperationResult


class Harness:
    """One synchronous local dispatch; no retries, workers, or transfer effects."""

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
        # Reserved for task 5.4; this increment never sleeps or retries.
        self._sleeper = sleeper

    def run(
        self, work: RequestUnitOfWork, operation: Operation, principal: Principal
    ) -> ExecuteOperationResult:
        if operation.request.tool not in (Tool.GET_BALANCE, Tool.SIMULATE_TRANSFER):
            raise Forbidden
        if operation.state != OperationState.READY:
            raise InvalidTransition("OPERATION_NOT_READY")
        # Transfer approval consumption/revalidation belongs to task 5.2.
        if operation.request.tool == Tool.SIMULATE_TRANSFER:
            raise ExecutionUnavailable
        if (
            operation.policy.decision != Decision.ALLOW
            or operation.policy.version != CURRENT_POLICY_VERSION
            or operation.request.tool not in principal.tools
            or operation.request.source not in principal.source_accounts
        ):
            raise Forbidden
        try:
            accounts = work.accounts.facts()
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
                or policy.decision != Decision.ALLOW
                or policy.version != CURRENT_POLICY_VERSION
            ):
                raise Forbidden
        except Exception:
            raise Forbidden from None
        args = operation.request.arguments
        if not isinstance(args, BalanceArguments):
            raise Forbidden
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
        try:
            result = self._tools.dispatch(operation.request.tool, args, accounts)
            if type(result) is not BalanceResult or result.account_id != args.account_id:
                raise ExecutionUnavailable
        except Exception:
            raise ExecutionUnavailable from None
        completed = operation.transition(OperationState.SUCCEEDED)
        work.operations.save_execution(completed, result)
        work.audit.append(completed.executed_event(self._clock.now()))
        return ExecuteOperationResult(completed, result)
