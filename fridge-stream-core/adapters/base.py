"""
Abstract base for platform adapters (Twitch, Kick, YouTube in this folder).

main.py builds one adapter per enabled platform (``PLATFORM_ADAPTERS``), calls
``start()`` / ``stop()`` and reads ``status_info()`` for the dashboard Status page.

Every adapter must:
  - connect / disconnect
  - push normalized ChatEvent objects onto the EventBus
  - periodically report viewer counts into MetricsAggregator
  - (optional) post Core's replies into the platform's chat: ``can_send`` says whether it
    can right now, ``send_message`` posts (main.py ``_post_reply`` calls both), and
    ``_remember_sent`` notes the text so the copy the platform echoes back is recognised
    (ChatEvent.from_core).
"""

from __future__ import annotations

import abc
import logging
import re
import time
from collections import deque
from typing import Optional

from core.alerts import build_alert
from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.models import ChatEvent, Platform

log = logging.getLogger("adapters.base")

CHAT_SUMMARY_SEC = 60.0   # seconds between the "N chat lines" summary lines in the console
# Core's own posted replies come back through the chat feed. A line whose text matches one
# sent in the last ECHO_WINDOW_SEC seconds is marked ChatEvent.from_core (and used up, so a
# viewer repeating it later is a normal line again). ECHO_COMPARE_CHARS: platforms may trim
# or re-space long text, so only the start is compared.
ECHO_WINDOW_SEC = 60.0
ECHO_COMPARE_CHARS = 120


def echo_key(text: str) -> str:
    """How sent text and echoed text are compared: spaces squashed, lower case, first
    ECHO_COMPARE_CHARS characters, a trailing "…" (from Core cutting long text) dropped."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip("…").strip()
    return t[:ECHO_COMPARE_CHARS]


class BaseAdapter(abc.ABC):
    """Shared state and helpers for one chat platform connection.

    Subclasses set ``platform``, implement ``start`` / ``stop``, and call ``_emit`` (chat),
    ``_emit_removed`` (mod deletions) and ``_emit_alert`` (subs, raids, tips ...).
    """

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
        # why the last reply couldn't be posted into this chat ("" when it worked); shown on
        # the dashboard Status page next to the platform
        self.last_send_error = ""

    def _set_connected(self) -> None:
        """Mark the platform as connected and clear the last error."""
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
        """Dashboard status for this platform (read by main.py ``platform_info``)."""
        return {
            "state": self.state,
            "connected": bool(self.connected),
            "last_error": self.last_error,
            "last_message_at": self.last_message_at,
            "send_error": self.last_send_error,
        }

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin listening. Should return quickly; long-running work goes in background tasks."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """Disconnect and cancel background tasks. Also called on an adapter that failed to start."""
        ...

    def can_send(self) -> tuple[bool, str]:
        """(can post into chat right now, why not). main.py asks this before ``send_message``
        and uses the overlay when it is False. Adapters with a sign-in override it."""
        return False, "posting into this chat is not supported"

    async def send_message(self, text: str, reply_to_message_id: str = "",
                           reply_to_user: str = "") -> bool:
        """Post ``text`` into the platform's chat; True when the platform took it.

        ``reply_to_message_id`` is the platform's id of the chat line being answered
        (ChatEvent.message_id) so it shows as a threaded reply where the platform has those
        (Kick, Twitch); ``reply_to_user`` is the chatter's display name, for platforms without
        threads (YouTube puts "@name" in front). Called by main.py ``_post_reply``; must not
        raise. Implementations call ``_remember_sent`` with the exact text they posted.
        """
        log.debug("[%s] send_message not implemented: %s", self.platform.value, text)
        return False

    def _remember_sent(self, text: str) -> None:
        """Note text Core just posted, so its echo from the chat feed is recognised in ``_emit``."""
        sent = getattr(self, "_sent_recently", None)
        if sent is None:
            sent = self._sent_recently = deque(maxlen=50)
        key = echo_key(text)
        if key:
            sent.append((time.time(), key))

    def _forget_sent(self, text: str) -> None:
        """The post failed, so no echo will come: drop the note ``_remember_sent`` made."""
        sent = getattr(self, "_sent_recently", None)
        key = echo_key(text)
        if not sent or not key:
            return
        for i in range(len(sent) - 1, -1, -1):
            if sent[i][1] == key:
                del sent[i]
                return

    def _is_own_echo(self, event: ChatEvent) -> bool:
        """True (once) when ``event`` is a copy of something Core posted in the last ECHO_WINDOW_SEC."""
        sent = getattr(self, "_sent_recently", None)
        if not sent:
            return False
        now = time.time()
        while sent and now - sent[0][0] > ECHO_WINDOW_SEC:
            sent.popleft()
        key = echo_key(event.message)
        if not key:
            return False
        for i, (_, k) in enumerate(sent):
            # Kick / Twitch / YouTube may cut a long line, so a prefix match counts too
            if k == key or (len(key) >= 20 and (k.startswith(key) or key.startswith(k))):
                del sent[i]
                return True
        return False

    async def _emit(self, event: ChatEvent) -> None:
        """Hand one normalized chat line to the EventBus (commands, points, overlays listen there)."""
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
        if self._is_own_echo(event):
            event.from_core = True
        self.metrics.record_message()
        # submit_chat paces the line when chat smoothing is on (core/chat_pacer.py)
        submit = getattr(self.bus, "submit_chat", None) or self.bus.publish_chat
        await submit(event)

    async def _emit_removed(self, *, message_id: str = "", user_id: str = "", username: str = "",
                            everything: bool = False) -> None:
        """A mod took chat away on the platform: one message (``message_id``), everything a
        chatter said (timeout / ban: ``user_id`` and/or ``username``) or the whole chat."""
        if not (message_id or user_id or username or everything):
            return
        await self.bus.publish_chat_removed({
            "platform": self.platform.value, "message_id": str(message_id or ""),
            "user_id": str(user_id or ""), "username": str(username or "").lower().lstrip("@"),
            "all": bool(everything)})

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
        item: str = "",
        image: str = "",
        level: Optional[int] = None,
        event_id: str = "",
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
            item=item,
            image=image,
            level=level,
        )
        payload["source"] = "platform"
        if event_id:
            # the platform's own id for the event: the Paid list lists it once
            payload["event_id"] = str(event_id)
        # Platform user id when the event carries one, so Core can credit points
        # to the same identity the viewer chats with (else it matches by name).
        payload["user_id"] = str(user_id or "")
        log.info("[%s] alert %s: %s", self.platform.value, kind, payload["headline"])
        await self.bus.publish_alert(payload)
