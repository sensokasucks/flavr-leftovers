"""
Stream events feed: a short in-memory list of what just happened, for the Live controls page.

The dashboard's "Stream events" window (admin/admin.js, Live controls) polls
GET /api/admin/activity?after=<id> every few seconds and shows the newest lines first.
Nothing here is saved to disk: the list starts empty every time Core starts.

Kinds (the window's filter buttons use the same names, keep them in step with admin.js
LIVE_FEED_KINDS):
  alert    follows, subs, raids, Super Chats, gifts (main.py _on_alert)
  redeem   a chatter spent points on a chat reaction (core/reactions.py ReactionEngine.fire)
  command  a chat command that passed the router (main.py _on_chat)
  game     something a game plugin reports with ctx.activity(...) (core/plugin_api.py)
  flag     a chatter set off a custom chat flag (main.py, bus.on_flag)
  error    a logged error anywhere in Core, or a warning from a chat platform / plugin
           (ActivityLogHandler, attached in main.py _run)

The list lives on the EventBus as ``bus.activity`` so every part of Core that already has
the bus (plugins, reactions, adapters) can add to it without new wiring.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

# Lines kept in memory. The window shows the newest ones; older lines simply fall off.
MAX_ITEMS = 300
# The same error text again within this many seconds bumps a counter instead of a new line,
# so a platform that keeps failing to connect can't flood the window.
REPEAT_WINDOW_SEC = 60.0
KINDS = ("alert", "redeem", "command", "game", "flag", "error")


class ActivityLog:
    """Thread-safe ring buffer of feed lines. Each line gets a rising ``id``; the dashboard
    asks for lines after the last id it has, so it never shows one twice."""

    def __init__(self, max_items: int = MAX_ITEMS):
        self._items: deque = deque(maxlen=max_items)
        self._next_id = 1
        # Logging handlers can run on other threads (uvicorn, adapters' helper threads)
        self._lock = threading.Lock()

    def add(self, kind: str, text: str, platform: str = "", ts: Optional[float] = None) -> Optional[dict]:
        """Add one line. ``kind`` is one of KINDS (anything else is stored as "game");
        ``text`` is shown as-is (the dashboard escapes it). Returns the line, or None if empty."""
        text = " ".join(str(text or "").split())
        if not text:
            return None
        if kind not in KINDS:
            kind = "game"
        now = ts if ts is not None else time.time()
        with self._lock:
            last = self._items[-1] if self._items else None
            if (kind == "error" and last and last["kind"] == "error" and last["text"] == text[:300]
                    and now - last["ts"] < REPEAT_WINDOW_SEC):
                # Same error again: count it on the existing line and move it up as "new"
                last["count"] += 1
                last["ts"] = now
                last["id"] = self._next_id
                self._next_id += 1
                return last
            item = {"id": self._next_id, "ts": now, "kind": kind, "text": text[:300],
                    "platform": str(platform or ""), "count": 1}
            self._next_id += 1
            self._items.append(item)
            return item

    def since(self, after: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Lines with id > ``after``, oldest first, at most ``limit`` (the newest ones).
        ``last`` is the highest id so far, for the next call."""
        with self._lock:
            rows: List[dict] = [dict(i) for i in self._items if i["id"] > after]
            last = self._next_id - 1
        return {"items": rows[-max(1, min(int(limit), MAX_ITEMS)):], "last": last}


class ActivityLogHandler(logging.Handler):
    """Copies logged problems into the feed as "error" lines.

    Every ERROR (and worse) from anywhere, plus WARNINGs from the chat platform adapters and
    plugins, where a warning usually means "this isn't working right now". Ordinary warnings
    elsewhere stay in the console only, so the window isn't full of noise.
    """

    WARN_PREFIXES = ("adapters", "plugins", "core.plugins", "plugin.")
    # Picture / emote look-ups warn about every missing picture: too chatty for the window
    WARN_QUIET = ("adapters.kick_avatars", "adapters.twitch_avatars", "adapters.twitch_emotes")

    def __init__(self, log: ActivityLog):
        super().__init__(level=logging.WARNING)
        self.activity = log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.ERROR and (
                    not record.name.startswith(self.WARN_PREFIXES) or record.name.startswith(self.WARN_QUIET)):
                return
            msg = record.getMessage().splitlines()[0] if record.getMessage() else ""
            # "adapters.kick" -> "kick: ..." so the line says where it came from
            where = record.name.split(".")[-1]
            self.activity.add("error", f"{where}: {msg}", ts=record.created)
        except Exception:
            # A broken log line must never break logging itself
            pass
