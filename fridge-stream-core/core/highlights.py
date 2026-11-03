"""
Highlighted message: the streamer picks one chat line and it shows on its own overlay.

/overlay/highlight.html (an OBS browser source) draws the current highlight as a lower-third
bar: the chatter's picture, name, platform letter and the message with its emotes. The
streamer highlights a line from the dashboard (Chat & flags page, the Live page's chat
window) or from the phone remote; more highlights wait in a queue and Next moves on.

Who calls what:
  main.py _on_chat / _on_flagged_chat -> HighlightBoard.note_chat   every chat line (the
      recent list the dashboard and phone pick from, with emotes intact)
  api/admin_routes.py /api/admin/highlight*                        highlight / next / clear /
      settings / recent chat for the chat windows
  main.py StreamCore.start -> HighlightBoard.run                    the auto-hide timer
  HighlightBoard.on_change (main.py)                                broadcasts {"type":
      "highlight"} on /ws; the overlay and Stream Rooms (seat glow) listen for it
  HighlightBoard.on_featured (main.py)                              tells the end credits who
      was highlighted ("Featured" section, core/credits.py CreditsEngine.feature)

Settings: the ``highlight:`` block of config.yaml (Chat box page -> Highlighted message):
  hold_sec     seconds a highlight stays before the next one (0 = until Next / Clear)
  show_avatar  draw the chatter's picture
  read_aloud   reserved for text-to-speech; off by default and nothing reads it yet

Nothing here is saved to disk: the queue starts empty every time Core starts.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
import time
from collections import deque
from typing import Any, Awaitable, Callable, Dict, List, Optional

log = logging.getLogger("core.highlights")

# Chat lines kept for the chat windows to pick from (the dashboard and phone ask for the
# newest ones with ?after=<seq>). 300 lines is a few minutes of a very busy chat.
RECENT_MAX = 300
# Highlights waiting behind the one on screen. A 21st push drops the oldest waiting one.
QUEUE_MAX = 20
# Longest message text kept on a highlight (characters); longer lines end in "…".
TEXT_MAX = 500
# Emote pictures kept per highlight (a line of 200 emotes would make a very tall bar).
EMOTES_MAX = 80
# hold_sec is clamped to 0 .. HOLD_MAX seconds.
HOLD_MAX = 600
PLATFORMS = ("kick", "twitch", "youtube")

DEFAULTS: Dict[str, Any] = {"hold_sec": 0, "show_avatar": True, "read_aloud": False}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _clip(value: Any, n: int) -> str:
    """``value`` as a one-line string of at most ``n`` characters."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _web_url(value: Any) -> str:
    """An http(s) link, or "" (no javascript: or data: links reach the overlay)."""
    url = str(value or "").strip()
    return url[:500] if url.startswith(("https://", "http://")) else ""


def _local_url(value: Any) -> str:
    """Core's own chatter picture (/avatars/...), or ""."""
    url = str(value or "").strip()
    return url[:300] if url.startswith("/avatars/") and ".." not in url else ""


def clean_item(src: Dict[str, Any]) -> Dict[str, Any]:
    """A highlight built from a chat payload (main.py _on_chat "data") or the dashboard's copy
    of one. Only known fields pass, every string is clipped and links are checked, so the
    dashboard (or a phone) can't put anything odd on stream. The overlay still escapes all text."""
    user = src.get("user") if isinstance(src.get("user"), dict) else {}
    plat = str(src.get("platform") or "").lower()
    emotes = []
    for e in (src.get("emotes") or [])[:EMOTES_MAX]:
        if not isinstance(e, dict):
            continue
        try:
            start, end = int(e.get("start")), int(e.get("end"))
        except (TypeError, ValueError):
            continue
        url = _web_url(e.get("url"))
        if url and 0 <= start <= end:
            emotes.append({"start": start, "end": end, "url": url, "name": _clip(e.get("name"), 60),
                           "sticker": bool(e.get("sticker")), "gift": bool(e.get("gift"))})
    color = str(user.get("color") or "")
    # Emote ranges count characters of the full text, so the text is only cut when there are none
    raw = str(src.get("message") or "")
    message = raw[:2000] if emotes else _clip(raw, TEXT_MAX)
    return {
        "platform": plat if plat in PLATFORMS else "",
        "message_id": _clip(src.get("message_id"), 120),
        "message": message,
        "emotes": emotes,
        "user": {
            "id": _clip(user.get("id"), 80),
            "username": _clip(user.get("username"), 60),
            "display_name": _clip(user.get("display_name") or user.get("username"), 60),
            "color": color if _COLOR_RE.match(color) else "",
            "profile_image_url": _web_url(user.get("profile_image_url")),
            "avatar_local": _local_url(user.get("avatar_local")),
            "is_mod": bool(user.get("is_mod")),
            "is_vip": bool(user.get("is_vip")),
            "is_subscriber": bool(user.get("is_subscriber")),
        },
        "is_paid": bool(src.get("is_paid")),
        "paid_amount": _clip(src.get("paid_amount"), 30),
        "paid_currency": _clip(src.get("paid_currency"), 10),
    }


def quote_of(item: Dict[str, Any], n: int = 48) -> str:
    """A short quote of the highlighted text for the end credits (Kick emote tokens dropped)."""
    text = re.sub(r"\[emote:\d+:[^\]]+\]", "", str(item.get("message") or ""))
    text = " ".join(text.split())
    if not text:
        return ""
    return '"' + (text if len(text) <= n else text[: n - 1].rstrip() + "…") + '"'


class HighlightBoard:
    """The on-screen highlight, the queue behind it, and the recent chat lines to pick from.

    One instance on StreamCore (main.py) and core_state.highlights. Everything runs on Core's
    event loop; ``on_change`` / ``on_featured`` are set by main.py.
    """

    def __init__(self, config: Optional[dict] = None):
        self.settings: Dict[str, Any] = dict(DEFAULTS)
        # Each recent line gets a rising ``seq`` so a window asks only for newer lines.
        self.recent: deque = deque(maxlen=RECENT_MAX)
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)
        self.current: Optional[Dict[str, Any]] = None
        self.queue: List[Dict[str, Any]] = []
        # async (state dict) -> None: broadcast to /ws (main.py _send_highlight)
        self.on_change: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        # (platform, username, display_name, quote) -> None: credits "Featured" (main.py)
        self.on_featured: Optional[Callable[[str, str, str, str], None]] = None
        self.configure(config or {})

    # ── settings ──

    def configure(self, config: dict) -> None:
        """Read the ``highlight:`` block of the whole config (start, and after every save)."""
        cfg = (config or {}).get("highlight") or {}
        try:
            hold = int(float(cfg.get("hold_sec", DEFAULTS["hold_sec"]) or 0))
        except (TypeError, ValueError):
            hold = 0
        self.settings = {
            "hold_sec": max(0, min(HOLD_MAX, hold)),
            "show_avatar": bool(cfg.get("show_avatar", DEFAULTS["show_avatar"])),
            "read_aloud": bool(cfg.get("read_aloud", DEFAULTS["read_aloud"])),
        }

    # ── recent chat (what the dashboard / phone chat windows show) ──

    def note_chat(self, data: Dict[str, Any], *, flagged: bool = False) -> None:
        """Remember one chat line (main.py's chat payload "data"). Red-flagged chatters' lines
        are kept too, marked ``flagged``, so the streamer can see them; they can't be highlighted."""
        if not isinstance(data, dict) or data.get("from_core") or data.get("is_system"):
            return
        row = dict(data)
        row["seq"] = next(self._seq)
        row["flagged"] = bool(flagged)
        self.recent.append(row)

    def recent_since(self, after: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Lines with seq > ``after`` (oldest first, at most ``limit``) plus ``last``, the seq to
        pass back next time. ``after`` 0 = the newest ``limit`` lines."""
        last = self.recent[-1]["seq"] if self.recent else 0
        if after > last:
            # Core restarted (seq began again at 1): start the window over
            after = 0
        rows = [r for r in self.recent if r["seq"] > after]
        limit = max(1, min(int(limit or 100), RECENT_MAX))
        return {"items": rows[-limit:], "last": last, "reset": after == 0}

    def find(self, platform: str, message_id: str) -> Optional[Dict[str, Any]]:
        """The recent line with that platform + message id (newest first), or None."""
        if not message_id:
            return None
        for row in reversed(self.recent):
            if str(row.get("message_id") or "") == message_id and (not platform or row.get("platform") == platform):
                return row
        return None

    def forget_user(self, platform: str, user_id: str, username: str) -> None:
        """A chatter was red-flagged: mark their recent lines and take them off screen / queue."""
        name = (username or "").lower()

        def same(row: Dict[str, Any]) -> bool:
            u = row.get("user") or {}
            if platform and row.get("platform") != platform:
                return False
            return bool((user_id and str(u.get("id") or "") == str(user_id))
                        or (name and str(u.get("username") or "").lower() == name))

        for row in self.recent:
            if same(row):
                row["flagged"] = True
        self.queue = [q for q in self.queue if not same(q)]
        if self.current and same(self.current):
            self.current = None
            self._promote()

    # ── the highlight itself ──

    def push(self, source: Dict[str, Any], *, by: str = "dashboard") -> Dict[str, Any]:
        """Put a chat line on screen, or behind the one already there. Returns the new item.
        ``by`` (dashboard / phone) is kept for the Stream events feed."""
        item = clean_item(source)
        if not item["message"].strip() and not item["emotes"]:
            raise ValueError("That message is empty")
        item["id"] = next(self._ids)
        item["by"] = by
        item["queued_at"] = time.time()
        if self.current is None:
            self._show(item)
        else:
            self.queue.append(item)
            del self.queue[:-QUEUE_MAX]
        return item

    def _show(self, item: Optional[Dict[str, Any]]) -> None:
        """Make ``item`` the one on screen (None = nothing) and tell the credits about it."""
        self.current = item
        if item is None:
            return
        item["shown_at"] = time.time()
        if callable(self.on_featured):
            u = item.get("user") or {}
            try:
                self.on_featured(item.get("platform") or "", u.get("username") or "",
                                 u.get("display_name") or "", quote_of(item))
            except Exception:
                log.exception("credits featured hook failed")

    def _promote(self) -> None:
        """Nothing on screen: show the first one waiting, if any."""
        if self.current is None and self.queue:
            self._show(self.queue.pop(0))

    def next(self) -> None:
        """Take the current highlight off and show the next one waiting (or nothing)."""
        self.current = None
        self._promote()

    def clear(self) -> None:
        """Take everything off: the one on screen and the queue."""
        self.current = None
        self.queue = []

    def remove(self, item_id: int) -> bool:
        """Drop one waiting highlight (the dashboard's x on a queue row)."""
        before = len(self.queue)
        self.queue = [q for q in self.queue if q.get("id") != item_id]
        return len(self.queue) != before

    def state(self) -> Dict[str, Any]:
        """What the overlay, Stream Rooms and the dashboard need: the current item, the queue
        (short previews), and the look settings."""
        return {
            "current": self.current,
            "queue": [{"id": q["id"], "platform": q["platform"],
                       "name": (q.get("user") or {}).get("display_name") or "",
                       "message": _clip(q.get("message"), 80)} for q in self.queue],
            "queue_len": len(self.queue),
            "hold_sec": self.settings["hold_sec"],
            "show_avatar": self.settings["show_avatar"],
        }

    async def changed(self) -> None:
        """Broadcast the new state (call after push / next / clear / remove)."""
        if callable(self.on_change):
            try:
                await self.on_change(self.state())
            except Exception:
                log.exception("highlight broadcast failed")

    async def run(self, stop: Optional[asyncio.Event] = None) -> None:
        """Auto-hide loop (main.py starts it): with hold_sec > 0 a highlight moves on by itself
        after that many seconds. Checks twice a second."""
        while not (stop and stop.is_set()):
            await asyncio.sleep(0.5)
            hold = self.settings.get("hold_sec") or 0
            cur = self.current
            if hold and cur and time.time() - float(cur.get("shown_at") or 0) >= hold:
                self.next()
                await self.changed()
