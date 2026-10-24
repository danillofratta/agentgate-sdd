from typing import Protocol


class SleeperGateway(Protocol):
    def sleep(self, seconds: float) -> None: ...
