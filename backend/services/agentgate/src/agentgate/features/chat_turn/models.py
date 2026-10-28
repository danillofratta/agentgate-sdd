from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    action: Literal["message", "execute", "refresh", "retry"] = "message"
    message: Annotated[str, Field(max_length=2000)] = ""
    operation_id: (
        Annotated[
            str, Field(pattern=r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z")
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def valid_action(self) -> Self:
        if self.action == "message":
            valid = bool(self.message.strip()) and self.operation_id is None
        else:
            valid = not self.message and (self.operation_id is not None) == (self.action != "retry")
        if not valid:
            raise ValueError("INVALID_INPUT")
        return self
