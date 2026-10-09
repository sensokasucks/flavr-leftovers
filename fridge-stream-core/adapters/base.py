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
import time
from typing import Optional

from core.alerts import build_alert
from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.models import ChatEvent, Platform

log = logging.getLogger("adapters.base")

CHAT_SUMMARY_SEC = 60.0


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
        # What the dashboard shows (GET /api/admin/status):
        #   state  starting / connected / retrying / stopped
        #   last_error  one plain sentence on why it isn't connected ("" when fine)
        self.state = "starting"
        self.last_error = ""
        self.connected = False
        self.last_message_at: Optional[float] = None

    def _set_connected(self) -> None:
        self.state = "connected"
        self.connected = True
        self.last_error = ""

    def _set_retrying(self, reason: str) -> None:
        """Not connected right now, will try again by itself."""
        self.state = "retrying"
        self.connected = False
        self.last_error = str(reason or "").strip()

    def _set_stopped(self, reason: str = "") -> None:
        self.state = "stopped"
        self.connected = False
        if reason:
            self.last_error = str(reason).strip()

    def status_info(self) -> dict:
        return {
            "state": self.state,
            "connected": bool(self.connected),
            "last_error": self.last_error,
            "last_message_at": self.last_message_at,
        }

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
        now = time.time()
        self.last_message_at = now
        # Each chat line is logged at DEBUG by the adapter; the console gets one line a minute
        self._lines_this_minute = getattr(self, "_lines_this_minute", 0) + 1
        started = getattr(self, "_minute_started", 0.0)
        if not started:
            self._minute_started = now
        elif now - started >= CHAT_SUMMARY_SEC:
            log.info("[%s] %d chat lines in the last %.0f s", self.platform.value.title(),
                     self._lines_this_minute, now - started)
            self._lines_this_minute = 0
            self._minute_started = now
        if not self.connected:
            self._set_connected()
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
        viewers: Optional[int] = None,
        amount: Optional[float] = None,
        currency: str = "",
        message: str = "",
    ) -> None:
        """Sub / resub / gift / raid / tip seen on the platform → overlay alert on the bus.

        Core fills in `duration_ms` from `overlay.alert_duration_ms` (source=platform).
        """
        payload = build_alert(
            kind=kind,
            username=username,
            display_name=display_name,
            platform=self.platform.value,
            months=months,
            qty=qty,
            viewers=viewers,
            amount=amount,
            currency=currency,
            message=message,
        )
        payload["source"] = "platform"
        # Platform user id when the event carries one, so Core can credit points
        # to the same identity the viewer chats with (else it matches by name).
        payload["user_id"] = str(user_id or "")
        log.info("[%s] alert %s: %s", self.platform.value, kind, payload["headline"])
        await self.bus.publish_alert(payload)
