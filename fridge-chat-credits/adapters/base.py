"""Every platform adapter starts/stops and emits normalized ChatEvents."""

from __future__ import annotations

import abc
import logging

from core.event_bus import EventBus
from core.models import ChatEvent, Platform

log = logging.getLogger("adapters.base")


class BaseAdapter(abc.ABC):
    platform: Platform

    def __init__(self, config: dict, bus: EventBus):
        self.config = config
        self.bus = bus
        self._running = False

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    async def _emit(self, event: ChatEvent) -> None:
        await self.bus.publish_chat(event)
