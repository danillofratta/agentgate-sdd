import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

from agentgate.application.chat_conversation import ChatConversation
from agentgate.application.exceptions.agent_unavailable import AgentUnavailable


class ChatSessions:
    """Process-local, bounded, expiring chat only. Financial state stays in PostgreSQL."""

    def __init__(self, capacity: int = 64, ttl: float = 3600) -> None:
        self._capacity, self._ttl = capacity, ttl
        self._entries: dict[str, tuple[ChatConversation, asyncio.Lock, float]] = {}

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[ChatConversation]:
        now = monotonic()
        for key, (_, lock, touched) in list(self._entries.items()):
            if not lock.locked() and now - touched > self._ttl:
                del self._entries[key]
        if session_id not in self._entries:
            if len(self._entries) >= self._capacity:
                raise AgentUnavailable()
            self._entries[session_id] = (ChatConversation(), asyncio.Lock(), now)
        conversation, lock, _ = self._entries[session_id]
        # Reject overlapping turns instead of queuing stale user confirmations.
        if lock.locked():
            raise AgentUnavailable()
        async with lock:
            try:
                yield conversation
            finally:
                self._entries[session_id] = (conversation, lock, monotonic())
