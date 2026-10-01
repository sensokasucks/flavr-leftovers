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

from core.alerts import build_alert
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

    async def _emit_alert(
        self,
        kind: str,
        *,
        username: str,
        display_name: str = "",
        user_id: str = "",
        months: Optional[int] = None,
        qty: Optional[int] = None,
        message: str = "",
    ) -> None:
        """Sub / resub / gift seen on the platform → overlay alert on the bus.

        Core fills in `duration_ms` from `overlay.alert_duration_ms` (source=platform).
        """
        payload = build_alert(
            kind=kind,
            username=username,
            display_name=display_name,
            platform=self.platform.value,
            months=months,
            qty=qty,
            message=message,
        )
        payload["source"] = "platform"
        # Platform user id when the event carries one, so Core can credit points
        # to the same identity the viewer chats with (else it matches by name).
        payload["user_id"] = str(user_id or "")
        log.info("[%s] alert %s: %s", self.platform.value, kind, payload["headline"])
        await self.bus.publish_alert(payload)
