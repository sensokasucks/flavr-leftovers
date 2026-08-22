"""
Abstract base for platform adapters.

Every adapter must:
  - connect / disconnect
  - push normalized ChatEvent objects onto the EventBus
  - periodically report viewer counts into MetricsAggregator
  - (optional) send a reply message back to the platform
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.models import ChatEvent, Platform

log = logging.getLogger("adapters.base")


class BaseAdapter(abc.ABC):
    platform: Platform

    def __init__(
        self,
        config: dict,
        bus: EventBus,
        metrics: MetricsAggregator,
    ):
        self.config = config
        self.bus = bus
        self.metrics = metrics
        self._running = False

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin listening. Should return quickly; long-running work goes in background tasks."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    async def send_message(self, text: str, reply_to: Optional[ChatEvent] = None) -> bool:
        """Optional. Return True if the message was sent."""
        log.debug("[%s] send_message not implemented: %s", self.platform.value, text)
        return False

    async def _emit(self, event: ChatEvent) -> None:
        self.metrics.record_message()
        await self.bus.publish_chat(event)
