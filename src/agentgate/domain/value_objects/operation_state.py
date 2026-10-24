from enum import StrEnum


class OperationState(StrEnum):
    DENIED = "DENIED"
    READY = "READY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
