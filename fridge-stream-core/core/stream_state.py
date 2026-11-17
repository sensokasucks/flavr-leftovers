"""
Stream start and end: is the streamer live right now, on which platforms, and since when.

Who feeds it (through ``EventBus.report_live``, a no-op until main.py sets ``bus.stream``):

* Twitch: EventSub ``stream.online`` / ``stream.offline`` plus one Helix "is the channel live"
  look-up whenever the EventSub link (re)connects (adapters/twitch_eventsub.py). Needs the
  streamer's own Connect Twitch, like the paid events.
* Kick: the viewer poll that already runs every few seconds (adapters/kick.py
  ``_poll_viewers``, ``livestream.is_live``).
* YouTube: the chat adapter reaching the live chat counts as live; the chat ending counts as
  offline (adapters/youtube.py).

Rules (one "stream" can span several platforms and short drops):

* The stream STARTS when the first platform goes live while nothing was live.
* It ENDS when the last platform has been offline for ``stream.restart_grace_min`` minutes
  (default 15). Going live again inside that window is the same stream ("resumed"), so an
  OBS crash or an internet drop doesn't start a new credits session.
* Core restarting mid-stream keeps the stream: the state is saved in data/stream_state.json
  and a platform saying "live" again within the grace window resumes it.

Listeners (``add_listener``) get one dict per change:
  {"event": "started" | "dropped" | "resumed" | "ended", "live": bool, "platforms": [...],
   "started_at": unix s, "ended_at": unix s or None, "length_sec": int, "session": int}
main.py turns these into: a new credits session (credits.auto_session), a line in the Live
page's Stream events, a ``stream_state`` /ws frame and a push to the companion bot
(core/companion_link.py).

Everything here is synchronous apart from the end timer, so tests can drive it with a fake
clock (``clock``) and call ``check()`` instead of waiting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("core.stream_state")

PLATFORMS = ("twitch", "youtube", "kick")
DEFAULT_GRACE_MIN = 15.0
# Never treat a gap longer than this as "the same stream", whatever the setting says (minutes)
MAX_GRACE_MIN = 120.0

Listener = Callable[[Dict[str, Any]], None]


def read_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The ``stream:`` config block with defaults filled in and numbers clamped.

    ``restart_grace_min``: minutes all platforms may be offline before the stream counts as
    over (a drop shorter than this is the same stream). 0 ends it at once.
    """
    raw = dict((cfg or {}).get("stream") or {})
    try:
        grace = float(raw.get("restart_grace_min", DEFAULT_GRACE_MIN))
    except (TypeError, ValueError):
        grace = DEFAULT_GRACE_MIN
    return {"restart_grace_min": max(0.0, min(MAX_GRACE_MIN, grace))}


class StreamState:
    """One per Core (main.py). ``report()`` is called by the adapters; ``status()`` by the
    dashboard (GET /api/admin/stream) and the companion link's heartbeat."""

    def __init__(self, get_config: Callable[[], Dict[str, Any]], data_dir: Path,
                 clock: Callable[[], float] = time.time):
        self._get_config = get_config
        self.path = Path(data_dir) / "stream_state.json"
        self.clock = clock
        # platform -> {"live": bool, "since": unix s, "source": "eventsub" | "poll" | "chat" ...}
        self.platforms: Dict[str, Dict[str, Any]] = {}
        self.live = False                    # the stream as a whole (stays True during a drop)
        self.started_at: Optional[float] = None
        self.dropped_at: Optional[float] = None   # all platforms offline since; None = not dropped
        self.ended_at: Optional[float] = None
        self.session = 0                     # counts streams; a new number per "started"
        self.restarts = 0                    # drops that came back inside the grace window
        # last time Core saw the stream live (tick(), saved): after a crash, the drop counts from here
        self.alive_at: Optional[float] = None
        self._listeners: List[Listener] = []
        self._timer: Optional[asyncio.TimerHandle] = None
        self._load()

    # ── settings / listeners ───────────────────────────────────────────
    @property
    def grace_sec(self) -> float:
        return read_settings(self._get_config() or {})["restart_grace_min"] * 60.0

    def add_listener(self, fn: Listener) -> None:
        """``fn(change)`` after every start / drop / resume / end (see the module notes)."""
        self._listeners.append(fn)

    def _emit(self, event: str) -> None:
        change = self._change(event)
        log.info("Stream %s (%s)", event, ", ".join(change["platforms"]) or "no platform live")
        for fn in list(self._listeners):
            try:
                fn(change)
            except Exception:
                log.exception("stream state listener failed")

    def _change(self, event: str) -> Dict[str, Any]:
        now = self.clock()
        end = self.ended_at if event == "ended" else None
        length = int(((end or now) - self.started_at)) if self.started_at else 0
        return {"event": event, "live": self.live, "platforms": self.live_platforms(),
                "started_at": self.started_at, "ended_at": end, "length_sec": max(0, length),
                "session": self.session, "restarts": self.restarts}

    # ── reading ────────────────────────────────────────────────────────
    def live_platforms(self) -> List[str]:
        """Platforms live right now, in a fixed order (Twitch, YouTube, Kick)."""
        return [p for p in PLATFORMS if (self.platforms.get(p) or {}).get("live")]

    def status(self) -> Dict[str, Any]:
        """Dashboard / heartbeat view. ``state``: "offline", "live" or "dropped" (all platforms
        offline, waiting ``ends_in`` seconds for one to come back)."""
        now = self.clock()
        state = "offline"
        ends_in = None
        if self.live:
            state = "dropped" if self.dropped_at is not None else "live"
            if self.dropped_at is not None:
                ends_in = max(0, int(round(self.dropped_at + self.grace_sec - now)))
        return {"state": state, "live": self.live, "platforms": self.live_platforms(),
                "started_at": self.started_at, "ended_at": self.ended_at,
                "length_sec": int(now - self.started_at) if (self.live and self.started_at) else 0,
                "ends_in": ends_in, "session": self.session, "restarts": self.restarts,
                "sources": {p: dict(v) for p, v in self.platforms.items()},
                "grace_min": self.grace_sec / 60.0}

    # ── input ──────────────────────────────────────────────────────────
    def report(self, platform: str, live: bool, source: str = "") -> None:
        """One platform says it is live / offline now. Repeats of the same answer do nothing,
        so a poll may call this every time it runs."""
        platform = str(platform or "").lower()
        if platform not in PLATFORMS:
            return
        live = bool(live)
        prev = self.platforms.get(platform) or {}
        if bool(prev.get("live")) == live and prev:
            return
        self.platforms[platform] = {"live": live, "since": self.clock(), "source": source}
        log.info("%s %s (%s)", platform.title(), "is live" if live else "went offline", source or "?")
        any_live = bool(self.live_platforms())
        if any_live:
            if not self.live:
                self.live = True
                self.started_at = self.clock()
                self.ended_at = None
                self.dropped_at = None
                self.session += 1
                self.restarts = 0
                self.alive_at = self.started_at
                self._cancel_timer()
                self._save()
                self._emit("started")
            elif self.dropped_at is not None:
                self.dropped_at = None
                self.alive_at = self.clock()
                self.restarts += 1
                self._cancel_timer()
                self._save()
                self._emit("resumed")
            else:
                self._save()        # another platform joined; no event
        elif self.live and self.dropped_at is None:
            self.dropped_at = self.clock()
            self._save()
            if self.grace_sec <= 0:
                self._end()
            else:
                self._emit("dropped")
                self._arm_timer()
        else:
            self._save()

    def check(self) -> None:
        """End the stream if the grace window ran out (the timer calls this; tests call it)."""
        if self.live and self.dropped_at is not None and self.clock() >= self.dropped_at + self.grace_sec:
            self._end()

    def _end(self) -> None:
        self._cancel_timer()
        self.live = False
        self.ended_at = self.dropped_at or self.clock()
        self.dropped_at = None
        self._save()
        self._emit("ended")

    # ── timer (needs a running event loop; without one, check() is called by hand) ──
    def _arm_timer(self) -> None:
        self._cancel_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        wait = max(0.0, (self.dropped_at or self.clock()) + self.grace_sec - self.clock()) + 0.5
        self._timer = loop.call_later(wait, self.check)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def tick(self) -> None:
        """Called about every 2 s by main.py's metrics loop: while live, note "still live" in the
        file once a minute, so a Core that crashed knows when the stream was last seen."""
        if self.live and self.dropped_at is None:
            now = self.clock()
            if self.alive_at is None or now - self.alive_at >= 60:
                self.alive_at = now
                self._save()
        if self.live and self.dropped_at is not None and self._timer is None:
            self.check()

    def resume_timer(self) -> None:
        """main.py start(): after a restart, a stream saved as live gets the grace window to come
        back. Platforms are unknown until they report, so the stream counts as dropped from the
        last time it was seen live (``alive_at``); a Core started the next day ends it at once."""
        if self.live:
            if self.dropped_at is None:
                self.dropped_at = self.alive_at or self.clock()
            self.platforms = {}
            self.check()
            if self.live:
                self._arm_timer()

    # ── saving ─────────────────────────────────────────────────────────
    def _save(self) -> None:
        data = {"live": self.live, "started_at": self.started_at, "ended_at": self.ended_at,
                "dropped_at": self.dropped_at, "session": self.session, "restarts": self.restarts,
                "alive_at": self.alive_at}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.exception("could not save %s", self.path)

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.live = bool(data.get("live"))
        self.started_at = data.get("started_at")
        self.ended_at = data.get("ended_at")
        self.dropped_at = data.get("dropped_at")
        self.alive_at = data.get("alive_at")
        try:
            self.session = int(data.get("session") or 0)
            self.restarts = int(data.get("restarts") or 0)
        except (TypeError, ValueError):
            pass
