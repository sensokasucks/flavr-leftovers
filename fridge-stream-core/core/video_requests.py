"""
Video requests: viewers ask for YouTube videos, the streamer (or a mod) approves them, and the
approved ones play one after another on the video player page or the Stream Rooms big screen.

Where requests come from:
  core/discord_bot.py      a YouTube link posted in the Discord request channel (submit)
  api/video_request_routes.py  "Add a video" on the Live card (submit, source "dashboard")

Who decides:
  the Live card's Approve / Deny / Play now buttons (api/video_request_routes.py)
  the Approve / Deny / Play now buttons the bot posts in the Discord mod channel (discord_bot.py)
  Nothing plays without a yes: there is no auto-approve.

Where approved videos play (video_requests.play_on in config.yaml):
  "player"  the video player page, /overlay/video-player.html (overlay/video-player.js). It plays
            straight from YouTube with YouTube's own embedded player: no download, no convert.
            Add it in OBS as a Browser Source, and/or open it in a browser tab and share that tab
            to the Stream Rooms big screen with the sender page. It asks GET /api/video-requests/
            player every second and reports the end with POST .../player/ended.
  "rooms"   Stream Rooms downloads and converts the video and plays it on the big screen (the
            rooms "video" action, core/reactions.py ROOMS_ACTIONS). The next approved video is
            prepared ahead with the "video_prep" action, and the end is seen in the game's
            rooms_state "video" line (ended_n goes up; stream-rooms core/rooms_remote.gd).

The queue is saved to data/video_requests.json after every change, so it survives a restart.
Played / denied / failed requests are kept (last HISTORY_MAX) for the "already played" rule and
the Live card's History list.

Other modules listen with add_listener(fn): fn(item, change) is called after each change
("added", "approved", "denied", "playing", "played", "skipped", "failed", "removed"); the Discord
bot uses it to swap its reactions and update its mod-channel message.

Settings: the ``video_requests:`` block of config.yaml (DEFAULTS below, core/config.py). Keep
DEFAULTS, read_settings(), admin/discord.js (readRules / fillRules) and checklists/discord.md in step.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

log = logging.getLogger("core.video_requests")

DEFAULTS: Dict[str, Any] = {
    "enabled": False,          # requests taken at all (the Discord channel and the Live card's Add)
    "play_on": "player",       # "player" (video player page) or "rooms" (Stream Rooms downloads it)
    "auto_play": False,        # start the next approved video when one ends
    "max_seconds": 600,        # longest video taken, in seconds (0 = no limit)
    "per_person": 1,           # requests one person may have waiting (0 = no limit)
    "repeats": "session",      # "off" (allowed), "session" (not twice since Core started), "history"
    "deny_cooldown_sec": 300,  # after a denial that person waits this long before asking again
    "blocked_words": [],       # refused when the title or channel name holds one (any case)
    "bot_replies": True,       # the Discord bot answers in the channel (refused why / approved / denied)
    "now_playing_post": False, # the bot posts "Now playing: ..." in the request channel
    "player_volume": 80,       # the player page's volume, 0-100
    "show_title": True,        # the player page shows "title - requested by name" for a few seconds
    "title_seconds": 8,        # how long that title card stays
}

# Statuses a request goes through. "pending" -> approved -> playing -> played; or denied / failed /
# skipped. WAITING are the ones still in the queue.
WAITING = ("pending", "approved", "playing")
HISTORY_MAX = 200            # finished requests kept for "already played" and the History list
REPEATS = ("off", "session", "history")
PLAY_ON = ("player", "rooms")

# YouTube video ids are 11 characters of letters, digits, - and _.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LINK_RE = re.compile(r"https?://[^\s<>]+", re.I)
_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
             "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com")

# Sentences the bot and the Live card use for a refusal (also the deny reasons the card offers).
DENY_REASONS = ["Not suitable for the stream", "Too long", "Already played", "Not now, maybe later"]


def read_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """The ``video_requests:`` block with every key present, numbers clamped and lists cleaned."""
    raw = dict((config or {}).get("video_requests") or {})
    out = copy.deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if key in raw:
            out[key] = raw[key]
    out["enabled"] = bool(out["enabled"])
    out["auto_play"] = bool(out["auto_play"])
    out["bot_replies"] = bool(out["bot_replies"])
    out["now_playing_post"] = bool(out["now_playing_post"])
    out["show_title"] = bool(out["show_title"])
    out["play_on"] = out["play_on"] if out["play_on"] in PLAY_ON else "player"
    out["repeats"] = out["repeats"] if out["repeats"] in REPEATS else "session"
    for key, lo, hi in (("max_seconds", 0, 6 * 3600), ("per_person", 0, 50), ("deny_cooldown_sec", 0, 86400),
                        ("player_volume", 0, 100), ("title_seconds", 0, 60)):
        try:
            out[key] = max(lo, min(hi, int(out[key])))
        except (TypeError, ValueError):
            out[key] = DEFAULTS[key]
    words = out["blocked_words"]
    if isinstance(words, str):
        words = words.split(",")
    out["blocked_words"] = [w.strip().lower() for w in (words or []) if str(w).strip()][:200]
    return out


def youtube_id(url: str) -> str:
    """The 11-character video id in a YouTube link, or "" when it isn't one.
    Takes watch?v=, youtu.be/, /shorts/, /embed/ and /live/ links (live ones are refused later
    by the length check, since a live stream has no length)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if host not in _YT_HOSTS:
        return ""
    if host.endswith("youtu.be"):
        vid = parts.path.strip("/").split("/")[0]
    elif parts.path == "/watch":
        vid = (parse_qs(parts.query).get("v") or [""])[0]
    else:
        bits = [b for b in parts.path.split("/") if b]
        vid = bits[1] if len(bits) >= 2 and bits[0] in ("shorts", "embed", "live", "v") else ""
    return vid if _ID_RE.match(vid or "") else ""


def find_youtube_link(text: str) -> str:
    """The first YouTube link in a chat line / Discord message, or ""."""
    for m in _LINK_RE.finditer(text or ""):
        link = m.group(0).rstrip(").,>!")
        if youtube_id(link):
            return link
    return ""


def fmt_length(seconds: Optional[int]) -> str:
    """12:05 / 1:02:03; "?" when unknown."""
    if seconds is None:
        return "?"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


async def look_up(video_id: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """What YouTube says about a video, without an API key.

    Returns {ok, title, channel, thumb, length (seconds or None), live, embeddable, age_limited,
    error}. Title and channel come from YouTube's public oEmbed address (it answers 401 / 403 for
    videos that can't be embedded or are private, 404 for missing ones). The length, live and age
    flags come from the public watch page; when that page can't be read they stay unknown (None /
    False) and the request still goes on the queue, marked "length unknown"."""
    info: Dict[str, Any] = {"ok": False, "title": "", "channel": "", "thumb": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                            "length": None, "live": False, "embeddable": True, "age_limited": False, "error": ""}
    own = client is None
    client = client or httpx.AsyncClient(timeout=8.0, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                                  "Accept-Language": "en-US,en;q=0.8"},
                                         cookies={"CONSENT": "YES+1"})
    watch = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r = await client.get("https://www.youtube.com/oembed", params={"url": watch, "format": "json"})
        if r.status_code in (401, 403):
            info["error"] = "That video can't be played outside YouTube (embedding is off, or it's private)."
            info["embeddable"] = False
            return info
        if r.status_code == 404:
            info["error"] = "YouTube can't find that video."
            return info
        if r.status_code == 200:
            data = r.json()
            info["title"] = str(data.get("title") or "")[:200]
            info["channel"] = str(data.get("author_name") or "")[:100]
            info["thumb"] = str(data.get("thumbnail_url") or info["thumb"])
        try:
            page = await client.get(watch)
            text = page.text if page.status_code == 200 else ""
        except httpx.HTTPError:
            text = ""
        m = re.search(r'"lengthSeconds":"(\d+)"', text)
        if m:
            info["length"] = int(m.group(1))
        info["live"] = '"isLiveContent":true' in text and ('"isLive":true' in text or info["length"] in (None, 0))
        info["embeddable"] = '"playableInEmbed":false' not in text
        info["age_limited"] = ('"status":"LOGIN_REQUIRED"' in text and "age" in text.lower()) or \
            '"status":"AGE_VERIFICATION_REQUIRED"' in text or '"isFamilySafe":false' in text
        info["ok"] = bool(info["title"]) or bool(text)
        if not info["ok"]:
            info["error"] = "YouTube didn't answer; try again in a moment."
    except (httpx.HTTPError, ValueError) as e:
        info["error"] = f"YouTube didn't answer ({e.__class__.__name__}); try again in a moment."
    finally:
        if own:
            await client.aclose()
    return info


Listener = Callable[[Dict[str, Any], str], Any]


class VideoRequestQueue:
    """The request queue. One per Core (main.py makes it as StreamCore.video_requests /
    core_state.video_requests). All methods are called on Core's event loop."""

    def __init__(self, get_config: Callable[[], Dict[str, Any]], data_dir: Path,
                 send_stage: Optional[Callable[[str, Any], Awaitable[bool]]] = None,
                 rooms_state: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
                 note: Optional[Callable[[str, str], None]] = None,
                 lookup: Callable[..., Awaitable[Dict[str, Any]]] = look_up) -> None:
        # get_config: the live config (settings are read on every use, so a save applies at once)
        # send_stage: ReactionEngine.send_stage (the rooms actions), rooms_state: its last rooms_state
        # note: a line for the Live page's Stream events window, lookup: look_up (tests pass a fake)
        self._get_config = get_config
        self._file = Path(data_dir) / "video_requests.json"
        self._send_stage = send_stage
        self._rooms_state = rooms_state
        self._note = note or (lambda text, kind: None)
        self._lookup = lookup
        self.items: List[Dict[str, Any]] = []     # waiting requests in play order, then history
        self._seq = 0                              # last request id handed out
        self._listeners: List[Listener] = []
        self._started = time.time()               # "session" repeats = since this moment
        self._denied_at: Dict[str, float] = {}    # person key -> time of their last denial
        self._player_seq = 0                       # goes up whenever the player page must reload its video
        self._rooms_ended_n: Optional[int] = None  # last rooms_state video.ended_n seen
        self._prepped: str = ""                    # the link last sent to Stream Rooms with video_prep
        self.player_paused = False                 # the Live card's Pause (player page only)
        self._load()

    # ── settings / persistence ──────────────────────────────────────────
    @property
    def settings(self) -> Dict[str, Any]:
        return read_settings(self._get_config() or {})

    def _load(self) -> None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            self.items = [i for i in items if isinstance(i, dict) and i.get("id")]
        self._seq = max([int(i.get("id", 0)) for i in self.items] + [int(data.get("seq", 0) or 0)])
        # a video "playing" when Core stopped isn't playing any more: back to the front as approved
        for i in self.items:
            if i.get("status") == "playing":
                i["status"] = "approved"

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"seq": self._seq, "items": self.items}, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._file)
        except OSError:
            log.exception("Couldn't save %s", self._file)

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def _changed(self, item: Dict[str, Any], change: str) -> None:
        """Save, then tell the listeners (Discord bot). A listener's coroutine runs as a task."""
        self._trim_history()
        self._save()
        for fn in list(self._listeners):
            try:
                res = fn(item, change)
                if asyncio.iscoroutine(res):
                    asyncio.ensure_future(res)
            except Exception:  # noqa: BLE001 - a broken listener must not stop the queue
                log.exception("video request listener failed")

    def _trim_history(self) -> None:
        done = [i for i in self.items if i.get("status") not in WAITING]
        if len(done) > HISTORY_MAX:
            drop = {id(i) for i in done[: len(done) - HISTORY_MAX]}
            self.items = [i for i in self.items if id(i) not in drop]

    # ── reading ─────────────────────────────────────────────────────────
    def get(self, rid: int) -> Optional[Dict[str, Any]]:
        for i in self.items:
            if int(i.get("id", 0)) == int(rid):
                return i
        return None

    def waiting(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return [i for i in self.items if i.get("status") in WAITING and (status is None or i.get("status") == status)]

    def playing(self) -> Optional[Dict[str, Any]]:
        return next((i for i in self.items if i.get("status") == "playing"), None)

    def history(self, limit: int = 30) -> List[Dict[str, Any]]:
        done = [i for i in self.items if i.get("status") not in WAITING]
        done.sort(key=lambda i: float(i.get("finished") or i.get("decided") or i.get("created") or 0), reverse=True)
        return done[:limit]

    def state(self) -> Dict[str, Any]:
        """What the Live card shows (api/video_request_routes.py GET)."""
        rooms = (self._rooms_state() if self._rooms_state else None) or {}
        video = rooms.get("video") if isinstance(rooms.get("video"), dict) else {}
        return {"settings": self.settings, "playing": self.playing(), "pending": self.waiting("pending"),
                "approved": self.waiting("approved"), "history": self.history(),
                "player_paused": self.player_paused, "rooms_connected": bool(rooms),
                "rooms_job": {"state": str(video.get("job") or ""), "text": str(video.get("job_text") or "")},
                "deny_reasons": DENY_REASONS}

    def player_state(self) -> Dict[str, Any]:
        """What the player page needs (GET /api/video-requests/player). seq changes whenever it
        must (re)load: a new video, a skip, Play now."""
        s = self.settings
        cur = self.playing() if s["play_on"] == "player" else None
        return {"seq": self._player_seq, "paused": self.player_paused, "volume": s["player_volume"],
                "show_title": s["show_title"], "title_seconds": s["title_seconds"],
                "current": None if cur is None else {"id": cur["id"], "video_id": cur["video_id"], "title": cur.get("title", ""),
                                                      "by": cur.get("by", ""), "channel": cur.get("channel", "")}}

    # ── submitting ──────────────────────────────────────────────────────
    def _person_key(self, source: str, by_id: str, by: str) -> str:
        return f"{source}:{by_id or by.lower()}"

    async def submit(self, url: str, by: str, source: str = "discord", by_id: str = "",
                     ref: Optional[Dict[str, Any]] = None, bypass_rules: bool = False) -> Dict[str, Any]:
        """A new request. Returns {"ok": True, "item"} or {"ok": False, "reason"} (plain words for
        the bot's reply / the card). bypass_rules: the streamer's own Add on the Live card skips
        the per-person, repeat, cooldown, length and blocked-word rules (never the YouTube
        checks: live, age-restricted, not embeddable)."""
        s = self.settings
        if not s["enabled"]:
            return {"ok": False, "reason": "Video requests are switched off right now."}
        vid = youtube_id(url)
        if not vid:
            return {"ok": False, "reason": "That isn't a YouTube video link."}
        person = self._person_key(source, by_id, by)
        if not bypass_rules:
            denied = self._denied_at.get(person, 0.0)
            wait = s["deny_cooldown_sec"] - (time.time() - denied)
            if denied and wait > 0:
                return {"ok": False, "reason": f"Please wait {int(wait // 60) + 1} min before asking again."}
            mine = [i for i in self.waiting() if i.get("person") == person]
            if s["per_person"] and len(mine) >= s["per_person"]:
                return {"ok": False, "reason": "You already have a video waiting. One at a time!"}
            if any(i.get("video_id") == vid for i in self.waiting()):
                return {"ok": False, "reason": "That video is already in the queue."}
            if s["repeats"] != "off":
                since = self._started if s["repeats"] == "session" else 0.0
                if any(i.get("video_id") == vid and i.get("status") == "played" and float(i.get("finished") or 0) >= since
                       for i in self.items):
                    return {"ok": False, "reason": "That video was already played."}
        info = await self._lookup(vid)
        if info.get("error") and not info.get("ok"):
            return {"ok": False, "reason": info["error"]}
        if info.get("live"):
            return {"ok": False, "reason": "Live streams can't be requested, only videos."}
        if info.get("age_limited"):
            return {"ok": False, "reason": "Age-restricted videos can't be played on stream."}
        if not info.get("embeddable", True) and s["play_on"] == "player":
            return {"ok": False, "reason": "That video can't be played outside YouTube."}
        length = info.get("length")
        # the length limit and blocked words are for viewers; the streamer's own Add skips them too
        if not bypass_rules and s["max_seconds"] and length is not None and length > s["max_seconds"]:
            return {"ok": False, "reason": f"That video is {fmt_length(length)} long; the limit is {fmt_length(s['max_seconds'])}."}
        hay = f"{info.get('title', '')} {info.get('channel', '')}".lower()
        if not bypass_rules and any(w in hay for w in s["blocked_words"]):
            return {"ok": False, "reason": "That video can't be requested here."}
        self._seq += 1
        item = {"id": self._seq, "url": f"https://www.youtube.com/watch?v={vid}", "video_id": vid,
                "title": info.get("title") or vid, "channel": info.get("channel", ""), "thumb": info.get("thumb", ""),
                "length": length, "by": (by or "someone")[:60], "by_id": str(by_id)[:40], "person": person,
                "source": source, "status": "pending", "reason": "", "created": time.time(),
                "decided": None, "decided_by": "", "finished": None, "ref": dict(ref or {})}
        self.items.append(item)
        self._note(f"Video request from {item['by']}: {item['title']} ({fmt_length(length)})", "command")
        self._changed(item, "added")
        return {"ok": True, "item": item}

    # ── deciding ────────────────────────────────────────────────────────
    def approve(self, rid: int, by: str = "streamer") -> Dict[str, Any]:
        item = self.get(rid)
        if item is None:
            return {"ok": False, "reason": "That request is gone."}
        if item["status"] != "pending":
            return {"ok": False, "reason": f"Already {item['status']} by {item.get('decided_by') or 'someone'}."}
        item.update(status="approved", decided=time.time(), decided_by=by[:60])
        # approved ones go after the other approved ones, before the pending ones (play order)
        self.items.remove(item)
        last = max([n for n, i in enumerate(self.items) if i.get("status") in ("approved", "playing")], default=-1)
        self.items.insert(last + 1, item)
        self._changed(item, "approved")
        self._prep_next()
        return {"ok": True, "item": item}

    def deny(self, rid: int, by: str = "streamer", reason: str = "") -> Dict[str, Any]:
        item = self.get(rid)
        if item is None:
            return {"ok": False, "reason": "That request is gone."}
        if item["status"] not in ("pending", "approved"):
            return {"ok": False, "reason": f"Already {item['status']}."}
        item.update(status="denied", decided=time.time(), decided_by=by[:60], reason=reason[:200], finished=time.time())
        self._denied_at[item.get("person", "")] = time.time()
        self._changed(item, "denied")
        return {"ok": True, "item": item}

    def remove(self, rid: int) -> Dict[str, Any]:
        """Take a request out without telling anyone it was denied (a mistake, a duplicate)."""
        item = self.get(rid)
        if item is None or item["status"] == "playing":
            return {"ok": False, "reason": "Can't remove that one now."}
        self.items.remove(item)
        self._changed(item, "removed")
        return {"ok": True}

    def move(self, rid: int, step: int) -> Dict[str, Any]:
        """Approved list: move a video up (-1) or down (+1) the play order."""
        approved = self.waiting("approved")
        item = self.get(rid)
        if item is None or item not in approved:
            return {"ok": False, "reason": "Only approved videos can be moved."}
        n = approved.index(item)
        m = max(0, min(len(approved) - 1, n + (1 if step > 0 else -1)))
        if m == n:
            return {"ok": True}
        other = approved[m]
        a, b = self.items.index(item), self.items.index(other)
        self.items[a], self.items[b] = other, item
        self._save()
        self._prep_next()
        return {"ok": True}

    # ── playing ─────────────────────────────────────────────────────────
    async def play(self, rid: Optional[int] = None, by: str = "streamer") -> Dict[str, Any]:
        """Play a request now: a given one (Play now, approving it on the way), or the next
        approved one (Play next). Whatever was playing counts as skipped."""
        if rid is not None:
            item = self.get(rid)
            if item is None or item["status"] not in ("pending", "approved"):
                return {"ok": False, "reason": "That request can't be played now."}
            if item["status"] == "pending":
                item.update(status="approved", decided=time.time(), decided_by=by[:60])
                self._changed(item, "approved")
        else:
            approved = self.waiting("approved")
            if not approved:
                return {"ok": False, "reason": "No approved videos waiting."}
            item = approved[0]
        cur = self.playing()
        if cur is not None:
            self._finish(cur, "skipped")
        item["status"] = "playing"
        item["started"] = time.time()
        # the playing one sits first, so "approved" order stays the play order after it
        self.items.remove(item)
        self.items.insert(0, item)
        self._player_seq += 1
        self.player_paused = False
        ok = await self._start_on_screen(item)
        if not ok:
            item["status"] = "failed"
            item["reason"] = "Stream Rooms isn't connected."
            item["finished"] = time.time()
            self._changed(item, "failed")
            return {"ok": False, "reason": "Stream Rooms isn't connected, so it couldn't play there."}
        self._note(f"Now playing: {item['title']} (requested by {item['by']})", "command")
        self._changed(item, "playing")
        self._prep_next()
        return {"ok": True, "item": item}

    async def _start_on_screen(self, item: Dict[str, Any]) -> bool:
        if self.settings["play_on"] != "rooms":
            return True       # the player page picks it up on its next poll (player_seq changed)
        if self._send_stage is None:
            return False
        # remember the game's end count now, so only a NEW end moves the queue on
        rooms = (self._rooms_state() if self._rooms_state else None) or {}
        video = rooms.get("video") if isinstance(rooms.get("video"), dict) else {}
        self._rooms_ended_n = int(video.get("ended_n") or 0)
        return await self._send_stage("video", item["url"])

    def _finish(self, item: Dict[str, Any], status: str, reason: str = "") -> None:
        item.update(status=status, finished=time.time())
        if reason:
            item["reason"] = reason[:200]
        self._changed(item, status)

    async def skip(self) -> Dict[str, Any]:
        """Stop the video playing now; with auto-play on, the next one starts."""
        cur = self.playing()
        if cur is None:
            return {"ok": False, "reason": "Nothing is playing."}
        self._finish(cur, "skipped")
        self._player_seq += 1
        if self.settings["play_on"] == "rooms" and self._send_stage is not None:
            await self._send_stage("stop", True)
        if self.settings["auto_play"] and self.waiting("approved"):
            await self.play()
        return {"ok": True}

    async def ended(self, rid: Optional[int] = None) -> None:
        """The video reached its end (player page, or Stream Rooms' ended_n went up). rid: the
        player says which video ended, so an old page's late report can't end a newer video."""
        cur = self.playing()
        if cur is None or (rid is not None and int(rid) != int(cur["id"])):
            return
        self._finish(cur, "played")
        self._player_seq += 1
        if self.settings["auto_play"] and self.waiting("approved"):
            await self.play()

    async def failed(self, rid: int, reason: str) -> None:
        """The player page couldn't play it (YouTube error: removed, not embeddable ...)."""
        cur = self.playing()
        if cur is None or int(rid) != int(cur["id"]):
            return
        self._finish(cur, "failed", reason)
        self._player_seq += 1
        if self.settings["auto_play"] and self.waiting("approved"):
            await self.play()

    def set_paused(self, on: bool) -> None:
        self.player_paused = bool(on)
        self._player_seq += 1

    def _prep_next(self) -> None:
        """Stream Rooms only: have the game download / convert the next approved video ahead
        (rooms action "video_prep"), so it starts at once. One at a time: the game runs one
        download job, so only the first waiting video is sent, and only once."""
        if self.settings["play_on"] != "rooms" or self._send_stage is None:
            return
        approved = self.waiting("approved")
        if not approved or approved[0]["url"] == self._prepped:
            return
        nxt = approved[0]["url"]
        self._prepped = nxt
        asyncio.ensure_future(self._send_stage("video_prep", nxt))

    async def watch_rooms(self, stop: asyncio.Event) -> None:
        """Background task (main.py): checks Stream Rooms' "video" line once a second. A new end
        (ended_n went up since the video started) moves the queue on, like the player's report."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            if self.settings["play_on"] != "rooms":
                continue
            cur = self.playing()
            rooms = (self._rooms_state() if self._rooms_state else None) or {}
            video = rooms.get("video") if isinstance(rooms.get("video"), dict) else None
            if cur is None or video is None or self._rooms_ended_n is None:
                continue
            n = int(video.get("ended_n") or 0)
            if n > self._rooms_ended_n:
                self._rooms_ended_n = n
                try:
                    await self.ended(cur["id"])
                except Exception:  # noqa: BLE001
                    log.exception("moving the video queue on failed")
