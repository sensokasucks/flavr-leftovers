"""
Twitch chat emotes for the chat payload.

Two sources, both turned into the same list of ranges on ChatEvent.emotes:

  * Native Twitch emotes: the IRC ``emotes`` tag (``25:0-4,12-16/1902:6-10``).
    Positions are Unicode code points, which is what Python ``str`` indexes.
  * Third-party emotes (BetterTTV, FrankerFaceZ, 7TV): global sets plus the
    channel's own sets, looked up by the channel's Twitch id (IRC ``room-id``).
    Words in the message that exactly match an emote code become emotes.

Each entry::

    {"provider": "twitch" | "bttv" | "ffz" | "7tv", "id": str, "name": str,
     "start": int, "end": int,          # inclusive code-point range in the message
     "url": str,                        # 2x image (may be animated GIF / WebP)
     "static_url": str,                 # still image when the provider has one ("" otherwise)
     "animated": bool}

Consumers: the chat overlay (``overlay/chat.js``) and Stream Rooms' audience.
Read-only public APIs, no keys. Toggle: ``twitch.third_party_emotes``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger("adapters.twitch_emotes")

TWITCH_CDN = "https://static-cdn.jtvnw.net/emoticons/v2/{id}/{fmt}/dark/2.0"
BTTV_CDN = "https://cdn.betterttv.net/emote/{id}/2x"
REFRESH_SEC = 30 * 60


def parse_twitch_emotes(tag: str, message: str) -> list[dict]:
    """IRC ``emotes`` tag -> emote ranges (sorted by start)."""
    out: list[dict] = []
    if not tag:
        return out
    for group in tag.split("/"):
        if ":" not in group:
            continue
        emote_id, ranges = group.split(":", 1)
        for r in ranges.split(","):
            if "-" not in r:
                continue
            try:
                start, end = (int(x) for x in r.split("-", 1))
            except ValueError:
                continue
            if start < 0 or end < start or end >= len(message):
                continue
            out.append({
                "provider": "twitch",
                "id": emote_id,
                "name": message[start:end + 1],
                "start": start,
                "end": end,
                "url": TWITCH_CDN.format(id=emote_id, fmt="default"),
                "static_url": TWITCH_CDN.format(id=emote_id, fmt="static"),
                "animated": False,   # "default" serves GIF only for animated emotes
            })
    out.sort(key=lambda e: e["start"])
    return out


def strip_action(message: str) -> str:
    """``/me`` messages arrive as ``\\x01ACTION text\\x01``; emote positions refer to ``text``."""
    if message.startswith("\x01ACTION ") and message.endswith("\x01"):
        return message[8:-1]
    return message


def match_words(message: str, table: dict[str, dict], taken: list[dict]) -> list[dict]:
    """Whole words that are third-party emote codes, skipping ranges already taken."""
    if not table:
        return []
    busy = [(e["start"], e["end"]) for e in taken]
    out: list[dict] = []
    i = 0
    n = len(message)
    while i < n:
        if message[i].isspace():
            i += 1
            continue
        j = i
        while j < n and not message[j].isspace():
            j += 1
        word = message[i:j]
        emote = table.get(word)
        if emote and not any(s <= j - 1 and i <= e for s, e in busy):
            item = dict(emote)
            item.update({"name": word, "start": i, "end": j - 1})
            out.append(item)
        i = j
    return out


# ── third-party sets ────────────────────────────────────────────────
def _bttv(items: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in items or []:
        code, eid = e.get("code"), e.get("id")
        if not code or not eid:
            continue
        animated = bool(e.get("animated")) or e.get("imageType") == "gif"
        url = BTTV_CDN.format(id=eid)
        out[code] = {"provider": "bttv", "id": eid, "url": url,
                     "static_url": "" if animated else url, "animated": animated}
    return out


def _ffz(sets: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in (sets or {}).values():
        for e in s.get("emoticons") or []:
            name, urls = e.get("name"), e.get("urls") or {}
            url = urls.get("2") or urls.get("1") or ""
            if not name or not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            anim = e.get("animated") or {}
            anim_url = (anim.get("2") or anim.get("1") or "") if isinstance(anim, dict) else ""
            out[name] = {"provider": "ffz", "id": str(e.get("id", "")), "url": anim_url or url,
                         "static_url": url, "animated": bool(anim_url)}
    return out


def _seventv(emotes: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in emotes or []:
        name = e.get("name")
        data = e.get("data") or {}
        host = (data.get("host") or {}).get("url") or ""
        if not name or not host:
            continue
        if host.startswith("//"):
            host = "https:" + host
        animated = bool(data.get("animated"))
        out[name] = {"provider": "7tv", "id": str(e.get("id", "")), "url": host + "/2x.webp",
                     "static_url": host + "/2x_static.webp", "animated": animated}
    return out


class ThirdPartyEmotes:
    """BTTV / FFZ / 7TV lookup table for one Twitch channel, refreshed every 30 min."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.room_id: str = ""
        self.table: dict[str, dict] = {}
        self._loaded_at: float = 0.0
        self._task: Optional[asyncio.Task] = None

    def set_room(self, room_id: str) -> None:
        """Called with the IRC room-id; (re)loads when it changes or the table is stale."""
        if not self.enabled or not room_id:
            return
        stale = time.time() - self._loaded_at > REFRESH_SEC
        if room_id == self.room_id and not stale:
            return
        if self._task and not self._task.done():
            return
        self.room_id = room_id
        self._loaded_at = time.time()   # don't hammer the APIs if a fetch fails
        self._task = asyncio.create_task(self._load(room_id), name="twitch-3p-emotes")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    def match(self, message: str, taken: list[dict]) -> list[dict]:
        if not self.enabled:
            return []
        return match_words(message, self.table, taken)

    async def _load(self, room_id: str) -> None:
        import httpx  # local import keeps the parsing helpers testable without deps

        async def get(client: httpx.AsyncClient, url: str):
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.json()
                log.debug("%s -> HTTP %s", url, r.status_code)
            except Exception as e:  # network / JSON errors: skip that provider
                log.debug("%s failed: %s", url, e)
            return None

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            results = await asyncio.gather(
                get(client, "https://7tv.io/v3/emote-sets/global"),
                get(client, "https://api.betterttv.net/3/cached/emotes/global"),
                get(client, "https://api.frankerfacez.com/v1/set/global"),
                get(client, f"https://7tv.io/v3/users/twitch/{room_id}"),
                get(client, f"https://api.betterttv.net/3/cached/users/twitch/{room_id}"),
                get(client, f"https://api.frankerfacez.com/v1/room/id/{room_id}"),
            )
        g7, gb, gf, c7, cb, cf = results
        table: dict[str, dict] = {}
        # lowest priority first; channel sets override globals, 7TV wins ties
        if isinstance(gf, dict):
            wanted = {str(s) for s in gf.get("default_sets") or []}
            table.update(_ffz({k: v for k, v in (gf.get("sets") or {}).items() if not wanted or k in wanted}))
        if isinstance(gb, list):
            table.update(_bttv(gb))
        if isinstance(g7, dict):
            table.update(_seventv(g7.get("emotes")))
        if isinstance(cf, dict):
            table.update(_ffz(cf.get("sets")))
        if isinstance(cb, dict):
            table.update(_bttv((cb.get("channelEmotes") or []) + (cb.get("sharedEmotes") or [])))
        if isinstance(c7, dict):
            table.update(_seventv((c7.get("emote_set") or {}).get("emotes")))
        self.table = table
        log.info("Third-party emotes for room %s: %d (7TV/BTTV/FFZ)", room_id, len(table))
