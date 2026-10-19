"""
Simple in-process async event bus.

Adapters publish ChatEvents.
Core (and any other subscribers) listen.
Later this can be swapped for Redis/NATS without changing the rest of the code.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, List

from .models import ChatEvent, ChatReply, ExecuteRequest, MetricsSnapshot

log = logging.getLogger("core.event_bus")

# Handler signatures: every handler is an async function taking one argument (an event
# object, or a plain dict for alerts, user updates, removed chat and flags).
ChatHandler = Callable[[ChatEvent], Awaitable[None]]
ExecuteHandler = Callable[[ExecuteRequest], Awaitable[None]]
MetricsHandler = Callable[[MetricsSnapshot], Awaitable[None]]
ReplyHandler = Callable[[ChatReply], Awaitable[None]]
AlertHandler = Callable[[dict], Awaitable[None]]
UserUpdateHandler = Callable[[dict], Awaitable[None]]
RemovedHandler = Callable[[dict], Awaitable[None]]
FlagHandler = Callable[[dict], Awaitable[None]]


class EventBus:
    """One shared bus per Core process (built in main.py, which registers its handlers in start()).

    on_*() registers a handler, publish_*() awaits every handler in order. A handler that
    raises is logged and skipped, so one broken subscriber never stops the others.
    """
    def __init__(self):
        self._chat_handlers: List[ChatHandler] = []
        self._execute_handlers: List[ExecuteHandler] = []
        self._metrics_handlers: List[MetricsHandler] = []
        self._reply_handlers: List[ReplyHandler] = []
        self._alert_handlers: List[AlertHandler] = []
        self._user_update_handlers: List[UserUpdateHandler] = []
        self._removed_handlers: List[RemovedHandler] = []
        self._flag_handlers: List[FlagHandler] = []
        self._lock = asyncio.Lock()
        # Optional chat smoothing (core/chat_pacer.py): adapters go through submit_chat
        self.pacer = None

    def on_chat(self, handler: ChatHandler) -> None:
        """Every chat line after smoothing (main.py: command router, overlays, store, credits ...)."""
        self._chat_handlers.append(handler)

    def on_execute(self, handler: ExecuteHandler) -> None:
        """A chat command passed the router and should go to the game plugins."""
        self._execute_handlers.append(handler)

    def on_metrics(self, handler: MetricsHandler) -> None:
        """Metrics snapshots (about every 2 s from main.py's metrics loop, plus admin test sends)."""
        self._metrics_handlers.append(handler)

    def on_reply(self, handler: ReplyHandler) -> None:
        """Adapters / overlay bridge: Core wants to say something in chat."""
        self._reply_handlers.append(handler)

    def on_alert(self, handler: AlertHandler) -> None:
        """Follow / sub / raid / Super Chat / test alerts for the overlay."""
        self._alert_handlers.append(handler)

    def on_user_update(self, handler: UserUpdateHandler) -> None:
        """Late user info (e.g. a Kick profile picture looked up after the first message)."""
        self._user_update_handlers.append(handler)

    def on_chat_removed(self, handler: RemovedHandler) -> None:
        """A mod deleted a message, timed out / banned a chatter, or cleared the chat."""
        self._removed_handlers.append(handler)

    def on_flag(self, handler: FlagHandler) -> None:
        """A chatter set off one of the streamer's custom chat flags (core/chat_flags.py)."""
        self._flag_handlers.append(handler)

    async def publish_flag(self, payload: dict[str, Any]) -> None:
        for h in list(self._flag_handlers):
            try:
                await h(payload)
            except Exception:
                log.exception("flag handler error")

    async def publish_chat_removed(self, payload: dict[str, Any]) -> None:
        if self.pacer is not None:
            # a line still held back by smoothing is never shown
            self.pacer.drop(payload)
        for h in list(self._removed_handlers):
            try:
                await h(payload)
            except Exception:
                log.exception("chat_removed handler error")

    async def publish_user_update(self, payload: dict[str, Any]) -> None:
        for h in list(self._user_update_handlers):
            try:
                await h(payload)
            except Exception:
                log.exception("user_update handler error")

    async def submit_chat(self, event: ChatEvent) -> None:
        """A platform adapter read a chat line: smoothing (when on) paces it, then publish_chat."""
        if self.pacer is None:
            await self.publish_chat(event)
        else:
            await self.pacer.submit(event)

    async def publish_chat(self, event: ChatEvent) -> None:
        # Handlers are copied first so one may register / unregister while we loop.
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

    async def publish_reply(self, reply: ChatReply) -> None:
        """Send a chat reply to every reply handler; with none registered it is only logged."""
        handlers = list(self._reply_handlers)
        if not handlers:
            log.info("[reply/%s] %s", reply.platform.value, reply.message)
            return
        for h in handlers:
            try:
                await h(reply)
            except Exception:
                log.exception("reply handler error")

    async def publish_alert(self, payload: dict[str, Any]) -> None:
        """Send an alert dict (``kind``, ``headline``, ...) to every alert handler; logged when none."""
        handlers = list(self._alert_handlers)
        if not handlers:
            log.info("[alert/%s] %s", payload.get("kind"), payload.get("headline"))
            return
        for h in handlers:
            try:
                await h(payload)
            except Exception:
                log.exception("alert handler error")
