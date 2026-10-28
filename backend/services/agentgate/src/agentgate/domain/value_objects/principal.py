from dataclasses import dataclass

from agentgate.domain.enums.role import Role
from agentgate.domain.enums.tool import Tool
from agentgate.domain.exceptions.invariant_violation import InvariantViolation
from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.principal_id import PrincipalId


@dataclass(frozen=True)
class Principal:
    id: PrincipalId
    role: Role
    tools: frozenset[Tool]
    source_accounts: frozenset[AccountId]

    def __post_init__(self) -> None:
        if not isinstance(self.id, PrincipalId) or not isinstance(self.role, Role):
            raise InvariantViolation("INVALID_PRINCIPAL")
        if not isinstance(self.tools, frozenset) or any(
            not isinstance(t, Tool) for t in self.tools
        ):
            raise InvariantViolation("INVALID_PERMISSIONS")
        if not isinstance(self.source_accounts, frozenset) or any(
            not isinstance(a, AccountId) for a in self.source_accounts
        ):
            raise InvariantViolation("INVALID_PERMISSIONS")
