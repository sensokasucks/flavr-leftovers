"""In-process async bus. Adapters publish ChatEvents; the roster + API listen."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, List

from .models import ChatEvent

log = logging.getLogger("core.event_bus")

ChatHandler = Callable[[ChatEvent], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._chat_handlers: List[ChatHandler] = []

    def on_chat(self, handler: ChatHandler) -> None:
        self._chat_handlers.append(handler)

    async def publish_chat(self, event: ChatEvent) -> None:
        for handler in self._chat_handlers:
            try:
                await handler(event)
            except Exception:
                log.exception("chat handler failed")
