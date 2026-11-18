"""
Chat moments: notice when chat suddenly gets much busier during a stream (something happened),
and tell the companion bot, which lists them in its after-stream recap with a link to that point
in the VOD. Optionally makes a real Twitch clip of it through Twitch's own "Create Clip" API.

How a moment is spotted (``tick``, called every 2 s by main.py ``_metrics_loop``):
  * only while the stream is live (core/stream_state.py) and the companion link is on (moments
    only go to the bot, so with the link off nothing is spotted and no clip is made);
  * ``baseline`` = the median chat-per-minute of the last ``baseline_min`` minutes (default 10),
    leaving out the newest minute (the spike itself);
  * a moment = chat per minute at least ``factor`` x the baseline (default 3) AND at least
    ``min_cpm`` (default 20), with ``cooldown_min`` (default 5) since the last one, and at least
    3 minutes of samples first (no moment in the first minutes of a stream).

What happens then:
  * ``twitch_clips`` on (default OFF: clips show on the channel's public Clips page) and Twitch
    live: Core asks Twitch for a clip of the last ~30 s (Helix POST /clips, needs the
    ``clips:edit`` scope: press Reconnect on the Twitch card once). Kick and YouTube have no clip
    API, so those get the VOD timestamp only.
  * the companion bot gets ``moment`` {at, cpm, baseline, clip, clip_error} (core/companion_link.py;
    docs/CORE_LINK.md in flavr-bot), ``at`` being ~20 s before the spike was noticed (people
    react after the thing happens).

Settings: the ``moments:`` config block (DEFAULTS below). Nothing here posts in chat or changes the
stream; Twitch clips are the only thing it creates.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

log = logging.getLogger("core.chat_moments")

DEFAULTS: Dict[str, Any] = {
    "enabled": True,          # spot moments (only goes anywhere while the companion link is on)
    "factor": 3.0,            # chat per minute this many times the usual
    "min_cpm": 20,            # ... and at least this busy
    "baseline_min": 10,       # "usual" = median of the last N minutes
    "cooldown_min": 5,        # at most one moment per N minutes
    "twitch_clips": False,    # also make a real Twitch clip (public on the channel's Clips page)
}
REACTION_SEC = 20.0           # the moment is put this long before chat noticed it
WARMUP_SEC = 180.0            # samples needed before the first moment
RECENT_SEC = 60.0             # the newest minute is left out of the baseline


def read_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict((cfg or {}).get("moments") or {})
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    for k, lo, hi in (("factor", 1.5, 20.0), ("min_cpm", 1, 10000), ("baseline_min", 3, 60), ("cooldown_min", 1, 120)):
        try:
            out[k] = max(lo, min(hi, float(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULTS[k]
    out["enabled"] = bool(out["enabled"])
    out["twitch_clips"] = bool(out["twitch_clips"])
    return out


# () -> (clip url, why not); main.py passes the Twitch adapter's create_clip
MakeClip = Callable[[], Awaitable[Tuple[str, str]]]


class ChatMoments:
    def __init__(self, get_config: Callable[[], Dict[str, Any]], get_cpm: Callable[[], float],
                 is_live: Callable[[], bool], send: Callable[[Dict[str, Any]], None],
                 make_clip: Optional[MakeClip] = None, twitch_live: Callable[[], bool] = lambda: False,
                 link_on: Callable[[], bool] = lambda: True, clock: Callable[[], float] = time.time):
        self._get_config = get_config
        self._cpm = get_cpm
        self._live = is_live
        self._send = send
        self._make_clip = make_clip
        self._twitch_live = twitch_live
        self._link_on = link_on       # the companion link can send (else no moment and, above all, no clip)
        self.clock = clock
        self._samples: Deque[Tuple[float, float]] = deque()
        self._last: float = 0.0
        self.found = 0                # moments this run (dashboard / tests)

    def baseline(self, now: float, minutes: float) -> Optional[float]:
        """Median chat per minute of the window, the newest minute left out; None while warming up."""
        old = [c for t, c in self._samples if now - t >= RECENT_SEC]
        if not self._samples or now - self._samples[0][0] < WARMUP_SEC or len(old) < 10:
            return None
        return statistics.median(old)

    async def tick(self) -> Optional[Dict[str, Any]]:
        """One look (every 2 s). Returns the moment it sent, else None."""
        s = read_settings(self._get_config() or {})
        now = self.clock()
        if not s["enabled"] or not self._live() or not self._link_on():
            self._samples.clear()     # a new stream starts its baseline fresh
            return None
        cpm = float(self._cpm())
        self._samples.append((now, cpm))
        while self._samples and now - self._samples[0][0] > s["baseline_min"] * 60:
            self._samples.popleft()
        base = self.baseline(now, s["baseline_min"])
        if base is None or now - self._last < s["cooldown_min"] * 60:
            return None
        if cpm < s["min_cpm"] or cpm < s["factor"] * max(base, 1.0):
            return None
        self._last = now
        self.found += 1
        moment: Dict[str, Any] = {"at": now - REACTION_SEC, "cpm": round(cpm, 1), "baseline": round(base, 1)}
        if s["twitch_clips"] and self._make_clip is not None and self._twitch_live():
            try:
                url, why = await self._make_clip()
            except Exception as e:      # a clip is a bonus: never lose the moment over it
                url, why = "", f"could not reach Twitch ({type(e).__name__})"
            if url:
                moment["clip"] = url
            elif why:
                moment["clip_error"] = why
        log.info("Chat moment: %.0f lines/min (usually %.0f)%s", cpm, base,
                 f", clip {moment['clip']}" if moment.get("clip") else "")
        self._send(moment)
        return moment
