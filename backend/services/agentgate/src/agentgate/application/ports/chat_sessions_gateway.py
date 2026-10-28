from contextlib import AbstractAsyncContextManager
from typing import Protocol

from agentgate.application.chat_conversation import ChatConversation


class ChatSessionsGateway(Protocol):
    def hold(self, session_id: str) -> AbstractAsyncContextManager[ChatConversation]: ...
