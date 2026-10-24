from typing import Protocol


class OperationIdGeneratorGateway(Protocol):
    def next_id(self) -> str: ...
