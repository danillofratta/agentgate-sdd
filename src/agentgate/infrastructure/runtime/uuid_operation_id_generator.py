from uuid import uuid4


class UuidOperationIdGenerator:
    def next_id(self) -> str:
        return str(uuid4())
