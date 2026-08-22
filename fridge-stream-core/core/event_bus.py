"""
Simple in-process async event bus.

Adapters publish ChatEvents.
Core (and any other subscribers) listen.
Later this can be swapped for Redis/NATS without changing the rest of the code.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List, Set

from .models import ChatEvent, ExecuteRequest, MetricsSnapshot

log = logging.getLogger("core.event_bus")

ChatHandler = Callable[[ChatEvent], Awaitable[None]]
ExecuteHandler = Callable[[ExecuteRequest], Awaitable[None]]
MetricsHandler = Callable[[MetricsSnapshot], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._chat_handlers: List[ChatHandler] = []
        self._execute_handlers: List[ExecuteHandler] = []
        self._metrics_handlers: List[MetricsHandler] = []
        self._lock = asyncio.Lock()

    def on_chat(self, handler: ChatHandler) -> None:
        self._chat_handlers.append(handler)

    def on_execute(self, handler: ExecuteHandler) -> None:
        self._execute_handlers.append(handler)

    def on_metrics(self, handler: MetricsHandler) -> None:
        self._metrics_handlers.append(handler)

    async def publish_chat(self, event: ChatEvent) -> None:
        handlers = list(self._chat_handlers)
        for h in handlers:
            try:
                await h(event)
            except Exception:
                log.exception("chat handler error")

    async def publish_execute(self, req: ExecuteRequest) -> None:
        handlers = list(self._execute_handlers)
        for h in handlers:
            try:
                await h(req)
            except Exception:
                log.exception("execute handler error")

    async def publish_metrics(self, snap: MetricsSnapshot) -> None:
        handlers = list(self._metrics_handlers)
        for h in handlers:
            try:
                await h(snap)
            except Exception:
                log.exception("metrics handler error")
