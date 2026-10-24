from typing import Protocol

from agentgate.application.ports.request_unit_of_work_gateway import RequestUnitOfWorkGateway


class RequestUnitOfWorkFactoryGateway(Protocol):
    def __call__(self) -> RequestUnitOfWorkGateway: ...
