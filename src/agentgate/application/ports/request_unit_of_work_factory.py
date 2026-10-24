from typing import Protocol

from agentgate.application.ports.request_unit_of_work import RequestUnitOfWork


class RequestUnitOfWorkFactory(Protocol):
    def __call__(self) -> RequestUnitOfWork: ...
