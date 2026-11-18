"""
Companion bot link: Core sends what it knows to an always-on helper bot on another PC at home
(the FlaVR Bot, its own repo: github.com/sensokasucks/flavr-bot). Off by default.

Direction: Core only SENDS. It opens no port and listens on nothing new (the "bind 127.0.0.1"
rule stays); the companion listens on its own PC and checks a shared password.

  POST {companion.url}/core/push
  Authorization: Bearer {companion.key}
  {"type": ..., "data": {...}, "at": unix seconds, "core": "stream-core"}

Types sent (the companion's docs/CORE_LINK.md is the other half of this list; keep in sync):
  hello      once when the link starts and on "Test" in the dashboard
  heartbeat  every ``heartbeat_sec`` (default 30): stream state (core/stream_state.py
             StreamState.status()), viewers, chat per minute, credits count. The companion pings
             the streamer's phone when these stop during a stream.
  stream     a start / drop / resume / end (StreamState listener change dict)
  alert      a real platform alert (raid, sub, gift, tip, Super Chat ...; never follows or tests):
             kind, platform, display_name, amount, currency, qty, months, viewers, headline
  snapshot   every 5 minutes and right after a stream ends: points leaderboard (top 500) and the
             video request queue, so the companion can answer /points and /queue while this PC is off
  chat       saved chat lines (Chat history, core/store.py chat_messages) the companion doesn't have
             yet, for its /said chat search: up to CHAT_BATCH lines with an id above the
             ``chat_since`` the companion put in its last answer, every CHAT_SEC, and at once
             again while a full batch went (catching up on old history). Switch: send_chat.
  moment     a sudden burst of chat during a stream (core/chat_moments.py): at, cpm, baseline and,
             with moments.twitch_clips, a Twitch clip link (or clip_error). For the bot's recap.
  chat_cleared  after Core deletes saved chat (store.on_chat_cleared): ``before`` for an age-only
             trim, nothing for any other clear (the companion then wipes its copy, answers
             chat_since 0 and gets what is left sent again)

Sending never blocks Core: ``send()`` puts the message on a small queue that one task drains.
Heartbeats and snapshots replace any older unsent one; stream events and alerts wait (up to
``QUEUE_MAX``) until the companion answers again. Settings: Setup → Discord & video requests →
Companion bot (admin/discord.js), saved in the ``companion:`` config block
(api/companion_routes.py). The key never leaves Core except in that header.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

log = logging.getLogger("core.companion_link")

DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "url": "",            # e.g. http://192.168.1.50:3870 (the companion PC on the home network)
    "key": "",            # shared password, the same as FLAVR_CORE_KEY on the companion
    "heartbeat_sec": 30,
    "send_alerts": True,
    "send_points": True,
    "send_queue": True,
    "send_chat": True,    # saved chat lines for the companion's /said search (only lines Core saves)
}
CHAT_SEC = 60.0           # new chat lines go to the companion this often
CHAT_BATCH = 1000         # lines per "chat" message
SNAPSHOT_SEC = 300.0      # points + queue copy this often (and after each stream end)
QUEUE_MAX = 200           # unsent stream events / alerts kept while the companion is away
RETRY_MAX = 120.0         # seconds between tries while the companion doesn't answer
REPLACED = ("heartbeat", "snapshot")   # only the newest of these matters
# Alerts not worth a phone ping or a record on the companion
SKIP_ALERT_KINDS = {"follow"}

# (after id, limit) -> saved chat rows with an id above it, oldest first (core/store.py chat_after)
ChatAfter = Callable[[int, int], Awaitable[list]]

# (url, json body, headers) -> (http status, json reply or {}); swapped for a fake in tests
Post = Callable[[str, Dict[str, Any], Dict[str, str]], Awaitable[Tuple[int, Any]]]


async def _post_httpx(url: str, body: Dict[str, Any], headers: Dict[str, str]) -> Tuple[int, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.post(url, json=body, headers=headers)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}


def read_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The ``companion:`` block with defaults; url without a trailing slash, numbers clamped."""
    raw = dict((cfg or {}).get("companion") or {})
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    out["enabled"] = bool(out["enabled"])
    out["url"] = str(out["url"] or "").strip().rstrip("/")
    if out["url"] and "://" not in out["url"]:
        out["url"] = "http://" + out["url"]
    out["key"] = str(out["key"] or "").strip()
    try:
        out["heartbeat_sec"] = max(10, min(300, int(out["heartbeat_sec"])))
    except (TypeError, ValueError):
        out["heartbeat_sec"] = DEFAULTS["heartbeat_sec"]
    for k in ("send_alerts", "send_points", "send_queue", "send_chat"):
        out[k] = bool(out[k])
    return out


def public_settings(s: Dict[str, Any]) -> Dict[str, Any]:
    """Settings for the dashboard: the key is replaced by ``key_set``."""
    out = {k: v for k, v in s.items() if k != "key"}
    out["key_set"] = bool(s.get("key"))
    return out


def alert_brief(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The few alert fields the companion needs, or None for alerts it never gets (tests, follows)."""
    if payload.get("is_test") or str(payload.get("kind") or "") in SKIP_ALERT_KINDS:
        return None
    keys = ("kind", "platform", "username", "display_name", "amount", "currency", "qty", "months",
            "viewers", "item", "level", "headline", "source")
    out = {k: payload.get(k) for k in keys if payload.get(k) not in (None, "")}
    msg = str(payload.get("message") or "")
    if msg:
        out["message"] = msg[:200]
    return out


class CompanionLink:
    """One per Core (main.py). ``heartbeat()`` and ``snapshot()`` are callbacks main.py gives it."""

    def __init__(self, get_config: Callable[[], Dict[str, Any]],
                 heartbeat: Callable[[], Dict[str, Any]],
                 snapshot: Callable[[], Awaitable[Dict[str, Any]]],
                 post: Optional[Post] = None, clock: Callable[[], float] = time.time,
                 chat_after: Optional[ChatAfter] = None):
        self._get_config = get_config
        self._heartbeat = heartbeat
        self._snapshot = snapshot
        self._post = post or _post_httpx
        self.clock = clock
        self._queue: Deque[Dict[str, Any]] = deque()
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.state = "off"            # off / on / retrying
        self.message = "The companion bot link is off."
        self.last_ok: Optional[float] = None
        self.sent = 0
        self._next_beat = 0.0
        self._next_snap = 0.0
        # chat for /said: main.py passes store.chat_after; chat_since comes from the companion's
        # answers (None until it has answered once: then Core knows where its copy ends)
        self._chat_after = chat_after
        self.chat_since: Optional[int] = None
        self._next_chat = 0.0
        self._chat_waiting = False      # a "chat" message is queued and not delivered yet

    # ── settings / status ──────────────────────────────────────────────
    @property
    def settings(self) -> Dict[str, Any]:
        return read_settings(self._get_config() or {})

    def why_not(self) -> str:
        """'' when the link may run, else what is missing (plain words for the dashboard)."""
        s = self.settings
        if not s["enabled"]:
            return "The companion bot link is off."
        if not s["url"]:
            return "Type the companion bot's address (like http://192.168.1.50:3870)."
        if not s["key"]:
            return "Type the shared password (the same one the companion bot has)."
        return ""

    def status(self) -> Dict[str, Any]:
        return {"state": self.state, "message": self.message, "last_ok": self.last_ok,
                "waiting": len(self._queue), "sent": self.sent}

    # ── sending ────────────────────────────────────────────────────────
    def send(self, kind: str, data: Dict[str, Any]) -> None:
        """Queue one message; never blocks. Does nothing while the link is off."""
        if self.why_not():
            return
        if kind in REPLACED:
            self._queue = deque(m for m in self._queue if m["type"] != kind)
        self._queue.append({"type": kind, "data": data, "at": self.clock(), "core": "stream-core"})
        while len(self._queue) > QUEUE_MAX:
            if self._queue.popleft()["type"] == "chat":
                self._chat_waiting = False      # read again from chat_since next time
        self._wake.set()

    def stream_changed(self, change: Dict[str, Any]) -> None:
        """StreamState listener: send the change, and a fresh snapshot after an end."""
        self.send("stream", dict(change))
        if change.get("event") == "ended":
            self._next_snap = 0.0
            self._wake.set()

    def alert(self, payload: Dict[str, Any]) -> None:
        """main.py ``_on_alert``: forward a real alert (see ``alert_brief``)."""
        if not self.settings["send_alerts"]:
            return
        brief = alert_brief(payload)
        if brief:
            self.send("alert", brief)

    def chat_cleared(self, before: Optional[float] = None) -> None:
        """core/store.py ``on_chat_cleared`` (main.py wires it): saved chat was deleted. ``before``:
        an age-only trim (lines older than that went); None: any other clear."""
        if not self.settings["send_chat"]:
            return
        self.send("chat_cleared", {"before": before} if before else {})

    async def _deliver(self, msg: Dict[str, Any]) -> Tuple[bool, str]:
        s = self.settings
        try:
            status, data = await self._post(f"{s['url']}/core/push", msg,
                                             {"Authorization": f"Bearer {s['key']}"})
        except Exception as e:
            return False, f"Can't reach the companion bot at {s['url']} ({type(e).__name__})."
        if status == 200 and isinstance(data, dict) and data.get("chat_since") is not None:
            try:
                since = int(data["chat_since"])               # an older bot doesn't send it: no chat
            except (TypeError, ValueError):
                since = None
            if since is not None:
                if self.chat_since is None or since < self.chat_since:
                    self._next_chat = 0.0       # first answer, or the bot's copy was wiped: send now
                self.chat_since = since
        if status == 401:
            return False, "The companion bot refused the password. Type the same one on both sides."
        if status != 200:
            why = data.get("error") if isinstance(data, dict) else ""
            return False, f"The companion bot answered HTTP {status}{': ' + why if why else ''}."
        return True, ""

    async def test(self) -> Dict[str, Any]:
        """Dashboard "Test": one hello, sent now. {ok, message}."""
        why = self.why_not()
        if why:
            return {"ok": False, "message": why}
        ok, err = await self._deliver({"type": "hello", "data": {"test": True}, "at": self.clock(),
                                       "core": "stream-core"})
        if ok:
            self.last_ok = self.clock()
            self._set("on", "Connected to the companion bot.")
        return {"ok": ok, "message": "The companion bot answered." if ok else err}

    def _set(self, state: str, message: str) -> None:
        if (state, message) != (self.state, self.message):
            (log.info if state != "retrying" else log.warning)("Companion link: %s", message)
        self.state, self.message = state, message

    # ── running ────────────────────────────────────────────────────────
    def start(self) -> None:
        self._stop.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="companion-link")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def restart(self) -> None:
        """Settings changed: send a hello and a heartbeat at once."""
        self._next_beat = 0.0
        self._next_snap = 0.0
        if not self.why_not():
            self.send("hello", {})
        self._wake.set()

    async def _due(self) -> None:
        """Queue a heartbeat / snapshot when their time has come."""
        now = self.clock()
        s = self.settings
        if now >= self._next_beat:
            self._next_beat = now + s["heartbeat_sec"]
            try:
                self.send("heartbeat", self._heartbeat())
            except Exception:
                log.exception("companion heartbeat failed")
        if now >= self._next_snap and (s["send_points"] or s["send_queue"]):
            self._next_snap = now + SNAPSHOT_SEC
            try:
                self.send("snapshot", await self._snapshot())
            except Exception:
                log.exception("companion snapshot failed")
        if (now >= self._next_chat and s["send_chat"] and self._chat_after is not None
                and self.chat_since is not None and not self._chat_waiting):
            self._next_chat = now + CHAT_SEC
            try:
                rows = await self._chat_after(self.chat_since, CHAT_BATCH)
            except Exception:
                log.exception("companion chat read failed")
                rows = []
            if rows:
                lines = [{"id": int(r["id"]), "platform": r.get("platform") or "", "username": r.get("username") or "",
                          "display_name": r.get("display_name") or "", "message": str(r.get("message") or "")[:2000],
                          "at": float(r.get("timestamp") or 0)} for r in rows]
                self.send("chat", {"lines": lines})
                self._chat_waiting = True
                if len(rows) >= CHAT_BATCH:
                    self._next_chat = 0.0       # catching up: the next batch right after this one

    async def _loop(self) -> None:
        backoff = 5.0
        first = True
        while not self._stop.is_set():
            self._wake.clear()          # anything sent from here on wakes the next sleep
            why = self.why_not()
            if why:
                self._queue.clear()
                self._chat_waiting = False
                self._set("off", why)
                first = True
                await self._sleep(15.0)
                continue
            if first:
                self.send("hello", {})
                first = False
            await self._due()
            failed = False
            while self._queue and not self._stop.is_set():
                ok, err = await self._deliver(self._queue[0])
                if not ok:
                    self._set("retrying", err + f" Trying again in {backoff:.0f} s.")
                    failed = True
                    break
                done = self._queue.popleft()
                if done["type"] == "chat":
                    self._chat_waiting = False
                self.sent += 1
                self.last_ok = self.clock()
                backoff = 5.0
                self._set("on", "Connected to the companion bot.")
            if failed:
                await self._sleep(backoff)
                backoff = min(backoff * 2, RETRY_MAX)
                continue
            nxt = min(self._next_beat, self._next_snap)
            if self.settings["send_chat"] and self._chat_after is not None:
                nxt = min(nxt, self._next_chat)
            wait = max(1.0, nxt - self.clock())
            await self._sleep(wait)

    async def _sleep(self, seconds: float) -> None:
        """Wait ``seconds``, or less when ``send()`` / ``stop()`` sets the wake flag."""
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
