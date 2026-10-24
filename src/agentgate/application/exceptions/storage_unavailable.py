class StorageUnavailable(Exception):
    """Durable storage could not confirm the requested outcome (HTTP 503)."""

    rollback_confirmed: bool = False
