import hmac

from agentgate.domain.value_objects.account_id import AccountId
from agentgate.domain.value_objects.principal import Principal
from agentgate.domain.value_objects.principal_id import PrincipalId
from agentgate.domain.value_objects.role import Role
from agentgate.domain.value_objects.tool import Tool
from agentgate.infrastructure.security.settings import Settings


class LocalCredentialGateway:
    def __init__(self, settings: Settings) -> None:
        self._agent_token = settings.agent_token
        self._approver_token = settings.approver_token
        self._agent = Principal(
            PrincipalId("principal-agent"),
            Role.AGENT,
            frozenset(Tool),
            frozenset({AccountId("acct-alice")}),
        )
        self._approver = Principal(
            PrincipalId("principal-approver"), Role.APPROVER, frozenset(), frozenset()
        )

    def verify(self, token: str) -> Principal | None:
        if not token.isascii() or len(token) > 512:
            return None
        agent = hmac.compare_digest(token, self._agent_token)
        approver = hmac.compare_digest(token, self._approver_token)
        if agent:
            return self._agent
        if approver:
            return self._approver
        return None

    def get_principal(self, principal_id: PrincipalId) -> Principal | None:
        for principal in (self._agent, self._approver):
            if principal.id == principal_id:
                return principal
        return None
