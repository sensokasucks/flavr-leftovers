"""In-process async pub/sub event bus."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict, List

Handler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subs: DefaultDict[str, List[Handler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if handler in self._subs[event_type]:
            self._subs[event_type].remove(handler)

    async def publish(self, event_type: str, payload: Any = None) -> None:
        handlers = list(self._subs.get(event_type, []))
        for h in handlers:
            try:
                result = h(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                print(f"[event_bus] handler error on {event_type}: {exc}")

    def clear(self) -> None:
        self._subs.clear()

    def on_chat(self, handler: Handler) -> None:
        self.subscribe("chat", handler)

    def on_execute(self, handler: Handler) -> None:
        self.subscribe("execute", handler)

    def on_metrics(self, handler: Handler) -> None:
        self.subscribe("metrics", handler)

    def on_alert(self, handler: Handler) -> None:
        self.subscribe("alert", handler)

    async def publish_chat(self, payload: Any) -> None:
        await self.publish("chat", payload)

    async def publish_execute(self, payload: Any) -> None:
        await self.publish("execute", payload)

    async def publish_metrics(self, payload: Any) -> None:
        await self.publish("metrics", payload)

    async def publish_alert(self, payload: Any) -> None:
        await self.publish("alert", payload)
