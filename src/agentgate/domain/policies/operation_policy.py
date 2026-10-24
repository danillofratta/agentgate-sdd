from agentgate.domain.value_objects.decision import Decision
from agentgate.domain.value_objects.policy_decision import PolicyDecision
from agentgate.domain.value_objects.policy_snapshot import PolicySnapshot
from agentgate.domain.value_objects.policy_version import PolicyVersion
from agentgate.domain.value_objects.reason import Reason
from agentgate.domain.value_objects.role import Role
from agentgate.domain.value_objects.transfer_arguments import TransferArguments

CURRENT_POLICY_VERSION = PolicyVersion("v1")


def evaluate_policy(snapshot: PolicySnapshot) -> PolicyDecision:
    version = CURRENT_POLICY_VERSION

    def deny(reason: Reason) -> PolicyDecision:
        return PolicyDecision(Decision.DENY, reason, version)

    principal, request = (snapshot.principal, snapshot.request)
    if principal.role != Role.AGENT:
        return deny(Reason.POLICY_UNCERTAIN)
    if request.tool not in principal.tools:
        return deny(Reason.TOOL_NOT_ALLOWED)
    if request.source not in principal.source_accounts:
        return deny(Reason.SOURCE_NOT_ALLOWED)
    accounts = {account.id: account for account in snapshot.accounts}
    if request.source not in accounts:
        return deny(Reason.UNKNOWN_ACCOUNT)
    args = request.arguments
    if isinstance(args, TransferArguments):
        if args.destination_account_id not in accounts:
            return deny(Reason.UNKNOWN_ACCOUNT)
        if args.amount.cents > accounts[request.source].balance_cents:
            return deny(Reason.INSUFFICIENT_FUNDS)
        if args.amount.cents > 100000:
            return deny(Reason.LIMIT_EXCEEDED)
        if args.amount.cents > 10000:
            return PolicyDecision(Decision.REQUIRE_APPROVAL, Reason.APPROVAL_REQUIRED, version)
    return PolicyDecision(Decision.ALLOW, Reason.PERMITTED, version)
