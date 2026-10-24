from agentgate.application.exceptions.storage_unavailable import StorageUnavailable


class TransientStorageLock(StorageUnavailable):
    """A SQLite lock/busy failure whose transaction is confirmed rolled back."""
