from enum import StrEnum


class OperationState(StrEnum):
    DENIED = "DENIED"
    READY = "READY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
