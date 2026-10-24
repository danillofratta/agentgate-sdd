from agentgate.application.exceptions.storage_unavailable import StorageUnavailable


class CommitUncertain(StorageUnavailable):
    """Commit acknowledgment failed; consult a fresh durable transaction."""
