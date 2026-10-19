"""
Chat smoothing: let chat lines out at an even pace instead of in bursts.

YouTube is read by polling, so its chat arrives as a clump of lines every few seconds.
With smoothing on for a platform, Core holds that platform's lines in a short queue and
lets them out one by one at the rate chat is really coming in, so overlays, Stream Rooms
and the credits see a steady trickle. Every chat handler (overlays, commands, points,
credits, chat history) gets the line at the same moment, once, when it leaves the queue.

Config (Settings -> Core + chat platforms -> Chat smoothing), all off by default:

  chat_smoothing:
    kick: false
    twitch: false
    youtube: false
    max_delay_sec: 5      # no line is held longer than this; a busy chat never falls behind

Each platform has its own queue, so a YouTube clump never holds up Twitch lines.
A line a mod deletes while it is still queued is dropped and never shown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Awaitable, Callable, Optional

from .models import ChatEvent

log = logging.getLogger("core.chat_pacer")

PLATFORMS = ("kick", "twitch", "youtube")
DEFAULT_MAX_DELAY = 5.0
MIN_MAX_DELAY = 1.0
MAX_MAX_DELAY = 30.0
# A gap this long between two lines starts a new clump (one poll's worth of chat)
BURST_GAP = 0.4
# First guess at the time between clumps, until a few have been seen
DEFAULT_PERIOD = 4.0
# Never let out lines more often than this (a flood still leaves at once via the deadline)
MIN_GAP = 0.02


def smoothing_settings(config: Optional[dict]) -> tuple[set[str], float]:
    """Platforms with smoothing on, and the longest a line may wait (seconds)."""
    sec = (config or {}).get("chat_smoothing") or {}
    if not isinstance(sec, dict):
        return set(), DEFAULT_MAX_DELAY
    on = {p for p in PLATFORMS if sec.get(p) is True}
    try:
        cap = float(sec.get("max_delay_sec", DEFAULT_MAX_DELAY))
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_DELAY
    if cap != cap:  # NaN
        cap = DEFAULT_MAX_DELAY
    return on, max(MIN_MAX_DELAY, min(MAX_MAX_DELAY, cap))


class _Lane:
    """One platform's queue and its pace."""

    def __init__(self) -> None:
        self.queue: deque[tuple[float, ChatEvent]] = deque()
        self.last_arrival = 0.0
        self.burst_start = 0.0
        self.burst_count = 0
        # lines per second chat really comes in at (0 = not known yet)
        self.rate = 0.0
        self.last_release = 0.0
        self.wake = asyncio.Event()
        self.task: Optional[asyncio.Task] = None

    def note_arrival(self, now: float) -> None:
        """Record one incoming line; when a new clump starts, update ``rate`` from the clump that ended.

        The rate is a moving average (60% old, 40% new) so one odd poll does not swing the pace.
        """
        if now - self.last_arrival >= BURST_GAP:
            if self.burst_start:
                # the clump just finished came in over the time until this one started
                seen = max(0.5, now - self.burst_start)
                inst = self.burst_count / seen
                self.rate = inst if not self.rate else 0.6 * self.rate + 0.4 * inst
            self.burst_start = now
            self.burst_count = 0
        self.burst_count += 1
        self.last_arrival = now

    def gap(self, now: float, max_delay: float) -> float:
        """Seconds to wait after the last release before letting the next line out."""
        if not self.queue:
            return 0.0
        rate = self.rate or self.burst_count / DEFAULT_PERIOD
        running = self.last_arrival - self.burst_start
        if running >= 1.0 and now - self.last_arrival < BURST_GAP:
            # chat that never pauses (Twitch, Kick) has no clumps: follow its live rate
            rate = max(rate, self.burst_count / running)
        gap = 1.0 / max(rate, 0.01)
        # Deadline: every queued line must be out before it has waited max_delay
        oldest_age = now - self.queue[0][0]
        left = max_delay - oldest_age
        if left <= 0:
            return 0.0
        gap = min(gap, left / len(self.queue))
        return max(MIN_GAP, gap)


class ChatPacer:
    """Sits between the adapters and the bus's chat handlers.

    ``deliver`` is the bus's real chat publish; ``get_config`` returns the live config.
    """

    def __init__(
        self,
        deliver: Callable[[ChatEvent], Awaitable[None]],
        get_config: Callable[[], Optional[dict]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._deliver = deliver
        self._get_config = get_config
        self._clock = clock
        self._lanes: dict[str, _Lane] = {}

    def settings(self) -> tuple[set[str], float]:
        """(platforms with smoothing on, max delay in seconds) from the live config; off if unreadable."""
        try:
            return smoothing_settings(self._get_config())
        except Exception:
            log.exception("chat smoothing settings unreadable; smoothing off")
            return set(), DEFAULT_MAX_DELAY

    def queued(self, platform: str = "") -> int:
        """Lines still held for ``platform``, or for every platform when it is ""."""
        if platform:
            lane = self._lanes.get(platform)
            return len(lane.queue) if lane else 0
        return sum(len(l.queue) for l in self._lanes.values())

    async def submit(self, event: ChatEvent) -> None:
        """Take one chat line from the bus: deliver it now, or queue it and make sure the lane's drain task runs."""
        platform = getattr(event.platform, "value", str(event.platform))
        on, _ = self.settings()
        lane = self._lanes.get(platform)
        if platform not in on:
            if lane and lane.queue:
                # smoothing was just switched off: let the held lines out first, in order
                await self._flush(lane)
            await self._deliver(event)
            return
        if lane is None:
            lane = self._lanes[platform] = _Lane()
        now = self._clock()
        lane.note_arrival(now)
        lane.queue.append((now, event))
        idle = lane.task is None or lane.task.done()
        if idle and len(lane.queue) == 1:
            _, max_delay = self.settings()
            if now - lane.last_release >= lane.gap(now, max_delay):
                # nothing waiting and the pace allows it: straight out, no extra delay
                lane.queue.popleft()
                lane.last_release = now
                await self._safe_deliver(event)
                return
        if lane.task is None or lane.task.done():
            lane.task = asyncio.create_task(self._drain(platform, lane), name=f"chat-pacer-{platform}")
        lane.wake.set()

    def drop(self, payload: dict) -> int:
        """A mod removed chat: forget matching lines that are still waiting. Returns how many."""
        platform = str(payload.get("platform") or "")
        lane = self._lanes.get(platform)
        if not lane or not lane.queue:
            return 0
        mid = str(payload.get("message_id") or "")
        uid = str(payload.get("user_id") or "")
        name = str(payload.get("username") or "").lower().lstrip("@")
        everything = bool(payload.get("all"))

        def gone(ev: ChatEvent) -> bool:
            if everything:
                return True
            if mid and str(ev.message_id or "") == mid:
                return True
            u = ev.user
            if uid and str(u.id) == uid:
                return True
            return bool(name) and name in (str(u.username or "").lower(), str(u.display_name or "").lower())

        keep = deque(item for item in lane.queue if not gone(item[1]))
        dropped = len(lane.queue) - len(keep)
        lane.queue = keep
        return dropped

    async def flush_all(self) -> None:
        """Let every held line out at once, in order (no pacing)."""
        for lane in list(self._lanes.values()):
            await self._flush(lane)

    async def _flush(self, lane: _Lane) -> None:
        """Deliver everything in one lane right now."""
        while lane.queue:
            _, ev = lane.queue.popleft()
            await self._safe_deliver(ev)
        lane.last_release = self._clock()

    async def _safe_deliver(self, event: ChatEvent) -> None:
        """Deliver one line; a failing handler is logged so the queue keeps moving."""
        try:
            await self._deliver(event)
        except Exception:
            log.exception("chat delivery failed")

    async def _drain(self, platform: str, lane: _Lane) -> None:
        """Background task per lane: let lines out one at a time at ``gap`` spacing until the queue is empty."""
        while lane.queue:
            on, max_delay = self.settings()
            if platform not in on:
                await self._flush(lane)
                return
            now = self._clock()
            wait = lane.last_release + lane.gap(now, max_delay) - now
            if wait > 0:
                lane.wake.clear()
                try:
                    # a new line (or a setting change) may shorten the wait: look again then
                    await asyncio.wait_for(lane.wake.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                continue
            if not lane.queue:
                break
            _, ev = lane.queue.popleft()
            lane.last_release = self._clock()
            await self._safe_deliver(ev)
