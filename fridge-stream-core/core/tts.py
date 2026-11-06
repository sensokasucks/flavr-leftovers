"""
Text-to-speech: Core sends lines to the streamer's own TTS server and plays what comes back.

Core ships no TTS software. The streamer runs a server that answers the OpenAI-style
``POST <server>/v1/audio/speech`` request (Kokoro-FastAPI, AllTalk, a Chatterbox server,
openedai-speech, Speaches, LocalAI, or a cloud service with an API key), usually on another PC
on the home network. Core sends ``{"model", "input", "voice", "response_format", "speed"}``,
saves the audio it gets back under data/tts/, and tells the overlays to play it:

    {"type": "tts", "data": {"id", "url": "/tts/<file>", "alert_id", "platform", "volume"}}

/overlay/alerts.html plays it (overlay/tts-player.js): a voice tied to an alert waits for that
alert to show and for its sound to end, and the alert stays up until the voice is done.
{"type": "tts_skip", "data": {"alert_id"}} tells it to stop waiting when no voice will come;
{"type": "tts_control", "data": {"action": "skip" | "clear"}} is the Skip / Clear buttons.

Who calls what (main.py makes one TtsEngine as StreamCore.tts / core_state.tts):
  main.py _on_alert          -> on_alert          alerts (follows, subs, raids ...) and paid ones
                                                  (Super Chats, bits, KICKs, tips ...); returns
                                                  {"wait_ms"} for the alert payload's "tts" key
  main.py _on_chat           -> handle_command    the !tts command (points cost, cooldown, who)
                             -> on_chat           chosen chat lines (who, 1 in N, gap)
  HighlightBoard.on_shown    -> on_highlight      the Highlighted message read aloud
  PluginContext.say          -> say_plugin        a game plugin's line (bus.say, set by main.py)
  api/tts_routes.py          -> settings page tools: check, test_audio, say_test, skip, clear,
                                pretend_down, replay, filter_test, status
  main.py StreamCore.start   -> run               the one worker: one line at a time

When the server is down: an alert never waits on its voice (the overlay gives up after
``wait_ms``). After FAIL_LIMIT failures in a row Core marks the server "down", stops sending,
and checks it again every RECHECK_SEC seconds; it comes back by itself. Paid messages and !tts
lines that couldn't be read go on the missed list (replay later); a missed !tts gets its points
back. The Stream events window gets one line when it goes down and one when it is back.

Settings: the ``tts:`` block of config.yaml (Setup -> Read aloud (TTS)); defaults in DEFAULTS
below and core/config.py. Keep the two, read_settings(), admin/tts.js and checklists/tts.md in step.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from core.cooldown import CooldownGate
from core.tts_text import TextFilter, strip_emotes

log = logging.getLogger("core.tts")

# Failures in a row before the server is marked "down" and Core stops sending to it.
FAIL_LIMIT = 3
# While down, seconds between checks (one short test line).
RECHECK_SEC = 30
# The text of that check (and of Check connection on the settings page).
CHECK_TEXT = "Testing, one two."
# Missed list size (paid messages and !tts lines that couldn't be read); oldest dropped.
MISSED_MAX = 50
# Recent lines log on the settings page.
RECENT_MAX = 20
# Audio files kept in data/tts/ (older ones are deleted as new ones are written).
KEEP_FILES = 40
# Extra time (ms) the overlay waits for an alert's voice on top of the server time limit.
WAIT_EXTRA_MS = 4000
# Audio formats Core asks for (``tts.server.format``) -> file ending and content type.
FORMATS = {"mp3": ("mp3", "audio/mpeg"), "wav": ("wav", "audio/wav"), "opus": ("opus", "audio/ogg"),
           "aac": ("aac", "audio/aac"), "flac": ("flac", "audio/flac")}
# What the server says it sent (content-type) -> file ending; anything else uses the asked format.
CTYPE_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
             "audio/wave": "wav", "audio/ogg": "opus", "audio/opus": "opus", "audio/aac": "aac",
             "audio/flac": "flac", "audio/x-flac": "flac"}
# Served at /tts/<name> (api/server.py tts_file): only names Core wrote itself.
FILE_RE = re.compile(r"^\d+-\d+\.(mp3|wav|opus|aac|flac)$")
# Alert kinds that count as paid messages (the "paid" trigger); every other kind but "flag"
# is the "alerts" trigger. Same money kinds as overlay/alerts.js GROUPS.money.
PAID_KINDS = ("superchat", "supersticker", "jewels", "bits", "kicks", "donation", "powerup",
              "celebration", "charity")
# Who may use a trigger: each level includes the ones after it (mods are also VIPs and subs).
WHO = ("everyone", "subs", "vips", "mods")
TRIGGERS = ("alerts", "paid", "command", "chat", "highlight", "plugins")
# Words a template may use; anything else in {braces} is left as typed.
_FIELD_RE = re.compile(r"\{(name|headline|message|amount)\}")

# Blocked chatters (work list item 19): "stream" lasts until Core restarts, "day" 24 hours,
# "forever" until unblocked. Saved in data/tts/blocked_people.json (the "stream" ones aren't).
BLOCK_FOR = {"stream": 0, "day": 24 * 3600, "forever": 0}
BLOCK_MAX = 500
# Read aloud "off for N minutes": the longest pause the Live card offers.
QUIET_MAX_MIN = 240
# How long a chatter's silhouette glows per character read (Stream Rooms), and the bounds.
GLOW_SEC_PER_CHAR = 0.07
GLOW_MIN_SEC, GLOW_MAX_SEC = 2.0, 30.0


def who_key(platform: Any, username: Any) -> str:
    """The key a blocked chatter is known by: "<platform>:<username>", lower case."""
    plat = str(getattr(platform, "value", platform) or "").lower().strip()
    return plat + ":" + str(username or "").lower().strip().lstrip("@")


DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "server": {
        # http://192.168.1.50:8880 (".../v1" and ".../v1/audio/speech" work too)
        "url": "",
        # tried when the first address doesn't answer; "" = none
        "backup_url": "",
        # sent as "Authorization: Bearer <key>"; most home servers need none
        "api_key": "",
        "model": "tts-1",
        "format": "mp3",
        # seconds Core waits for the audio of one line
        "timeout_sec": 15,
    },
    # the voice name every trigger uses unless it names its own (server-specific: "af_bella", "alloy" ...)
    "voice": "alloy",
    # 0.5 .. 2.0, sent to the server
    "speed": 1.0,
    # 0 .. 100, applied by the overlay
    "volume": 80,
    # longest line read (characters); longer ones are cut at a word ("cut") or not read ("skip")
    "max_chars": 300,
    "long_lines": "cut",
    # lines waiting to be read; past this, new lines are dropped (paid / !tts go to missed)
    "queue_max": 20,
    "filters": {
        "blocked": [],
        "on_match": "skip",       # skip | beep | remove
        "check_names": True,      # a blocked chatter name is read as "someone"
        "use_red_flags": False,   # also block the red-flag phrases (People -> Red flags)
        "drop_links": True,
    },
    "triggers": {
        "alerts": {"enabled": False, "voice": "", "template": "{headline} {message}"},
        "paid": {"enabled": False, "voice": "", "template": "{headline} {message}", "min_amount": 0},
        "command": {"enabled": False, "voice": "", "word": "tts", "cost": 100, "cooldown_sec": 60,
                    "who": "everyone", "template": "{name} says: {message}"},
        "chat": {"enabled": False, "voice": "", "who": "mods", "every_nth": 1, "min_gap_sec": 10,
                 "template": "{name} says: {message}"},
        "highlight": {"enabled": False, "voice": "", "template": "{name} says: {message}"},
        "plugins": {"enabled": False, "voice": ""},
    },
}


class TtsError(Exception):
    """The server didn't give audio. The message is plain words for the settings page."""


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def read_settings(config: Optional[dict]) -> Dict[str, Any]:
    """The ``tts:`` block of the whole config, filled from DEFAULTS and clamped. Never raises.
    An older config with only ``highlight.read_aloud`` turns the highlight trigger on from it."""
    raw = (config or {}).get("tts") or {}
    out = copy.deepcopy(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled", False))
    srv = raw.get("server") or {}
    s = out["server"]
    for key in ("url", "backup_url", "api_key", "model"):
        s[key] = " ".join(str(srv.get(key, s[key]) or "").split())[:300]
    s["model"] = s["model"] or "tts-1"
    fmt = str(srv.get("format") or "mp3").lower()
    s["format"] = fmt if fmt in FORMATS else "mp3"
    s["timeout_sec"] = int(_num(srv.get("timeout_sec"), 15, 3, 120))
    out["voice"] = " ".join(str(raw.get("voice", out["voice"]) or "").split())[:100]
    out["speed"] = round(_num(raw.get("speed"), 1.0, 0.5, 2.0), 2)
    out["volume"] = int(_num(raw.get("volume"), 80, 0, 100))
    out["max_chars"] = int(_num(raw.get("max_chars"), 300, 20, 1000))
    out["queue_max"] = int(_num(raw.get("queue_max"), 20, 1, 200))
    out["long_lines"] = "skip" if raw.get("long_lines") == "skip" else "cut"
    flt = raw.get("filters") or {}
    f = out["filters"]
    if isinstance(flt.get("blocked"), (list, str)):
        f["blocked"] = flt["blocked"]
    mode = str(flt.get("on_match") or "skip").lower()
    f["on_match"] = mode if mode in ("skip", "beep", "remove") else "skip"
    for key in ("check_names", "use_red_flags", "drop_links"):
        if key in flt:
            f[key] = bool(flt[key])
    trig = raw.get("triggers") or {}
    for name in TRIGGERS:
        have = trig.get(name) or {}
        t = out["triggers"][name]
        if name == "highlight" and "enabled" not in have:
            have = {**have, "enabled": bool(((config or {}).get("highlight") or {}).get("read_aloud"))}
        t["enabled"] = bool(have.get("enabled", False))
        t["voice"] = " ".join(str(have.get("voice") or "").split())[:100]
        if "template" in t:
            tpl = " ".join(str(have.get("template") or "").split())[:300]
            t["template"] = tpl or DEFAULTS["triggers"][name]["template"]
        if "who" in t:
            who = str(have.get("who") or t["who"]).lower()
            t["who"] = who if who in WHO else t["who"]
    pd = out["triggers"]["paid"]
    pd["min_amount"] = _num((trig.get("paid") or {}).get("min_amount"), 0, 0, 100000)
    cmd, have = out["triggers"]["command"], trig.get("command") or {}
    word = re.sub(r"[^a-z0-9_]", "", str(have.get("word") or "tts").lower().lstrip("!"))[:30]
    cmd["word"] = word or "tts"
    cmd["cost"] = int(_num(have.get("cost"), 100, 0, 10_000_000))
    cmd["cooldown_sec"] = int(_num(have.get("cooldown_sec"), 60, 0, 86400))
    chat, have = out["triggers"]["chat"], trig.get("chat") or {}
    chat["every_nth"] = int(_num(have.get("every_nth"), 1, 1, 1000))
    chat["min_gap_sec"] = int(_num(have.get("min_gap_sec"), 10, 0, 3600))
    return out


def speech_url(base: str) -> str:
    """The speech endpoint for what the streamer typed: "192.168.1.50:8880", "http://host:8880",
    ".../v1" and ".../v1/audio/speech" all give http(s)://host:port/v1/audio/speech."""
    url = (base or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "http://" + url
    if url.lower().endswith("/audio/speech"):
        return url
    if url.lower().endswith("/v1"):
        return url + "/audio/speech"
    return url + "/v1/audio/speech"


def voices_url(base: str) -> str:
    """Where a server lists its voices, when it does (Kokoro-FastAPI: GET /v1/audio/voices)."""
    url = speech_url(base)
    return url[: -len("/speech")] + "/voices" if url else ""


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc or url
    except ValueError:
        return url


def fill(template: str, **values: str) -> str:
    """``template`` with {name} {headline} {message} {amount} filled in (others left as typed)."""
    return " ".join(_FIELD_RE.sub(lambda m: str(values.get(m.group(1)) or ""), template or "").split())


def who_ok(user: Any, who: str) -> bool:
    """Whether a chatter (core.models.ChatUser, or a dict with is_mod / is_vip / is_subscriber)
    is in a trigger's ``who``: everyone | subs (subs, VIPs, mods) | vips (VIPs, mods) | mods."""
    get = (lambda k: bool(user.get(k))) if isinstance(user, dict) else (lambda k: bool(getattr(user, k, False)))
    mod, vip, sub = get("is_mod"), get("is_vip"), get("is_subscriber")
    if who == "mods":
        return mod
    if who == "vips":
        return mod or vip
    if who == "subs":
        return mod or vip or sub
    return True


@dataclass
class Job:
    """One line waiting to be read. ``keep`` = put it on the missed list if it can't be read
    (paid messages and !tts). ``refund`` = {"uid", "amount"} points to give back then."""

    id: int
    text: str
    voice: str
    trigger: str
    platform: str = ""
    name: str = ""
    alert_id: str = ""
    # "<platform>:<username>" in lower case, for blocking a chatter ("" = not a chatter's line)
    who: str = ""
    keep: bool = False
    refund: Optional[Dict[str, int]] = None
    created: float = field(default_factory=time.time)


class TtsEngine:
    """The text-to-speech queue, its one worker, the server state, the missed list and the log.

    ``get_config`` returns Core's live config; ``broadcast`` sends a dict to every /ws client;
    ``note(kind, text, platform)`` adds a Stream events line; ``store`` (core.store.Store) spends
    and refunds !tts points; ``is_admin(user)`` says who uses !tts for free (the streamer);
    ``prefix()`` is the command prefix ("!"); ``red_flag_phrases()`` the red-flag phrases.
    ``transport`` lets tests swap in a fake server (httpx.MockTransport).
    """

    def __init__(
        self,
        get_config: Callable[[], dict],
        data_dir: Path,
        broadcast: Optional[Callable[[dict], Awaitable[None]]] = None,
        note: Optional[Callable[..., None]] = None,
        store: Any = None,
        is_admin: Optional[Callable[[Any], bool]] = None,
        prefix: Callable[[], str] = lambda: "!",
        red_flag_phrases: Callable[[], List[str]] = lambda: [],
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.get_config = get_config
        self.dir = Path(data_dir) / "tts"
        self.broadcast = broadcast
        self.note = note
        self.store = store
        self.is_admin = is_admin or (lambda user: False)
        self.prefix = prefix
        self.red_flag_phrases = red_flag_phrases
        self.transport = transport
        self.pending: Deque[Job] = deque()
        self._wake = asyncio.Event()
        self._ids = itertools.count(1)
        self._files = itertools.count(1)
        # server state for the status light
        self.fails = 0
        self.down = False
        self.down_since = 0.0
        self.last_error = ""
        self.last_ok_at = 0.0
        self.last_try_at = 0.0
        self.last_seconds = 0.0
        # "Pretend the server is down" (settings page test switch); not saved
        self.pretend_down = False
        self.missed: List[Dict[str, Any]] = []
        self.recent: Deque[Dict[str, Any]] = deque(maxlen=RECENT_MAX)
        self.gate = CooldownGate()
        self._chat_seen = 0
        self._chat_last = 0.0
        self._filter_key: Any = None
        self._filter: Optional[TextFilter] = None
        # Live card controls (item 19): paused = hold the line (waiting lines stay), quiet_until =
        # "off for N minutes" (new lines are not read until then; paid / !tts go to missed)
        self.paused = False
        self.quiet_until = 0.0
        # the line playing now (sent to the overlays last), for the Live card
        self.now: Optional[Dict[str, Any]] = None
        # blocked chatters: who_key -> {platform, name, for, until, at}; until 0 = no end
        self.blocked_people: Dict[str, Dict[str, Any]] = self._load_blocked()

    # ── settings ──

    @property
    def settings(self) -> Dict[str, Any]:
        return read_settings(self.get_config() or {})

    def text_filter(self, settings: Optional[dict] = None) -> TextFilter:
        """The TextFilter for the current settings (rebuilt only when they change)."""
        s = settings or self.settings
        extra = list(self.red_flag_phrases() or []) if s["filters"]["use_red_flags"] else []
        key = (repr(s["filters"]), s["max_chars"], s["long_lines"], tuple(extra))
        if key != self._filter_key or self._filter is None:
            self._filter = TextFilter(s, extra)
            self._filter_key = key
        return self._filter

    def _trigger(self, name: str, s: Optional[dict] = None) -> Optional[dict]:
        """The trigger's settings when TTS and that trigger are on, else None."""
        s = s or self.settings
        if not s["enabled"]:
            return None
        t = s["triggers"][name]
        return t if t["enabled"] else None

    # ── log + queue ──

    def _log(self, trigger: str, text: str, result: str, why: str = "", voice: str = "",
             seconds: float = 0.0, name: str = "") -> None:
        """A row of the settings page's "Recent lines" (newest first there)."""
        self.recent.append({"at": time.time(), "trigger": trigger, "text": text[:160], "result": result,
                            "why": why, "voice": voice, "seconds": round(seconds, 2), "name": name})

    def _add_missed(self, job: Job, why: str) -> None:
        self.missed.append({"id": job.id, "at": time.time(), "trigger": job.trigger, "text": job.text,
                            "voice": job.voice, "platform": job.platform, "name": job.name, "why": why,
                            "refunded": int((job.refund or {}).get("amount") or 0)})
        del self.missed[:-MISSED_MAX]

    async def _refund(self, job: Job, why: str) -> None:
        """Give a !tts line's points back (once)."""
        ref, job.refund = job.refund, None
        if not ref or self.store is None:
            return
        try:
            await self.store.adjust_points(int(ref["uid"]), int(ref["amount"]), f"refund !tts ({why})", "tts")
        except Exception:
            log.exception("tts refund failed")

    async def _give_up(self, job: Job, why: str) -> None:
        """A line that won't be read: stop the overlay waiting, keep it on the missed list, refund."""
        if job.alert_id:
            await self._send({"type": "tts_skip", "data": {"alert_id": job.alert_id}})
        if job.keep:
            self._add_missed(job, why)
        await self._refund(job, why)

    def _queue(self, job: Job, s: dict) -> bool:
        """Put a job in line. False when the line is full, read aloud is off for a while
        (quiet_until) or the chatter is blocked (the caller gives up on it)."""
        if len(self.pending) >= s["queue_max"] or self.is_quiet() or (job.who and self.is_blocked(job.who)):
            return False
        self.pending.append(job)
        self._wake.set()
        return True

    def _refused_why(self, job: Job) -> str:
        """Why _queue said no, in words for the Recent lines list and the missed list."""
        if job.who and self.is_blocked(job.who):
            return "chatter blocked"
        if self.is_quiet():
            return "read aloud off for a while"
        return "queue full"

    async def enqueue(self, text: str, trigger: str, *, voice: str = "", platform: str = "", name: str = "",
                      alert_id: str = "", keep: bool = False, refund: Optional[dict] = None,
                      who: str = "") -> Optional[Job]:
        """Queue an already-cleaned line. Returns the job, or None when it wasn't taken (_queue)."""
        s = self.settings
        job = Job(id=next(self._ids), text=text, voice=voice or s["voice"], trigger=trigger, platform=platform,
                  name=name, alert_id=alert_id, keep=keep, refund=refund, who=who)
        if self._queue(job, s):
            return job
        why = self._refused_why(job)
        self._log(trigger, text, "skipped", why, job.voice, name=name)
        await self._give_up(job, why)
        return None

    def _queue_now(self, text: str, trigger: str, **kw) -> Optional[Job]:
        """enqueue() for callers that can't await (on_alert, on_chat, on_highlight). Never refunds:
        only !tts has points, and it awaits enqueue()."""
        s = self.settings
        job = Job(id=next(self._ids), text=text, voice=kw.pop("voice", "") or s["voice"], trigger=trigger, **kw)
        if self._queue(job, s):
            return job
        why = self._refused_why(job)
        self._log(trigger, text, "skipped", why, job.voice, name=job.name)
        if job.keep:
            self._add_missed(job, why)
        return None

    # ── triggers ──

    def on_alert(self, payload: dict) -> Optional[Dict[str, int]]:
        """An alert is about to go to the overlays (main.py _on_alert). Queues its voice when its
        trigger is on (paid kinds -> "paid", the rest -> "alerts"; a test alert only when the test
        asked for "read aloud"). Returns {"wait_ms"} for the payload's "tts" key, else None."""
        s = self.settings
        if not s["enabled"]:
            return None
        kind = str(payload.get("kind") or "")
        if kind == "flag":
            return None
        name = "paid" if kind in PAID_KINDS else "alerts"
        trig = s["triggers"][name]
        test = bool(payload.get("is_test"))
        if test and not payload.get("read_aloud"):
            return None
        if not test and not trig["enabled"]:
            return None
        if name == "paid" and not test and trig["min_amount"] > 0:
            try:
                amount = float(payload.get("amount"))
            except (TypeError, ValueError):
                amount = None
            cur = str(payload.get("currency") or "").lower()
            if amount is not None:
                value = amount / 100 if cur.startswith(("bit", "kick")) else amount
                if value < trig["min_amount"]:
                    return None
        flt = self.text_filter(s)
        display = str(payload.get("display_name") or payload.get("username") or "")
        spoken = flt.clean_name(display)
        headline = str(payload.get("headline") or "")
        if display and spoken != display:
            headline = headline.replace(display, spoken)
        message, _ = strip_emotes(str(payload.get("message") or ""))
        text = fill(trig["template"], name=spoken, headline=headline, message=message,
                    amount=str(payload.get("amount_fmt") or ""))
        text, why = flt.clean(text)
        trigger = name + (" (test)" if test else "")
        if why:
            self._log(trigger, headline, "skipped", why, name=spoken)
            return None
        job = self._queue_now(text, trigger, voice=trig["voice"], platform=str(payload.get("platform") or ""),
                              name=spoken, alert_id=str(payload.get("id") or ""), keep=name == "paid" and not test)
        if job is None:
            return None
        return {"wait_ms": s["server"]["timeout_sec"] * 1000 + WAIT_EXTRA_MS}

    async def handle_command(self, event: Any, *, dry_points: bool = False) -> Tuple[bool, str]:
        """The !tts command (main.py _on_chat, before reactions and chat games). Returns
        (taken, answer): taken = this was !tts, answer = what to say back in chat ("" = nothing).
        ``dry_points`` (the settings page's fake !tts) skips the points but says what it would cost."""
        s = self.settings
        trig = self._trigger("command", s)
        if trig is None:
            return False, ""
        raw = str(getattr(event, "message", "") or "")
        head = (self.prefix() or "!") + trig["word"]
        msg, _ = strip_emotes(raw, getattr(event, "emotes", None))
        if not msg.lower().startswith(head.lower()):
            return False, ""
        rest = msg[len(head):]
        if rest and not rest[0].isspace():
            return False, ""       # "!ttsx" is another command
        rest = rest.strip()
        user = event.user
        who = user.display_name or user.username
        if not rest:
            return True, f"@{who} type {head} and your message to have it read aloud."
        admin = bool(self.is_admin(user))
        wkey = who_key(user.platform, user.username)
        if not admin and self.is_blocked(wkey):
            return True, f"@{who} {head} isn't available to you right now."
        if not admin and not who_ok(user, trig["who"]):
            return True, f"@{who} {head} is only for {trig['who']} right now."
        key = f"tts|{user.platform.value if hasattr(user.platform, 'value') else user.platform}|{user.username}"
        wait = 0 if admin else self.gate.remaining(key, trig["cooldown_sec"])
        if wait > 0:
            return True, f"@{who} you can use {head} again in {int(wait + 0.999)} s."
        flt = self.text_filter(s)
        spoken = flt.clean_name(who)
        text, why = flt.clean(fill(trig["template"], name=spoken, message=rest))
        plat = getattr(user.platform, "value", user.platform) or ""
        if why:
            self._log("command", rest, "skipped", why, name=spoken)
            return True, f"@{who} that message can't be read aloud."
        cost = trig["cost"] if (((self.get_config() or {}).get("points") or {}).get("enabled") and not admin) else 0
        refund = None
        answer = ""
        if cost and dry_points:
            answer = f"(test) this would cost {cost} points."
        elif cost:
            if self.store is None:
                return True, ""
            uid = await self.store.get_or_create_user(plat, str(user.id or ""), user.username, user.display_name)
            got, balance = await self.store.spend_points(uid, cost, 1, f"!{trig['word']}", "tts")
            if not got:
                return True, f"@{who} {head} costs {cost} points, you have {balance}."
            refund = {"uid": int(uid), "amount": cost}
        self.gate.touch(key)
        job = await self.enqueue(text, "command", voice=trig["voice"], platform=plat, name=spoken,
                                 keep=True, refund=refund, who=wkey)
        if job is None:
            return True, f"@{who} the read-aloud line is full, try again soon" + (" (points given back)." if refund else ".")
        return True, answer

    def on_chat(self, event: Any) -> bool:
        """A chat line that wasn't a command (main.py _on_chat). Read when the chat trigger is on,
        the chatter is in its ``who``, it is the Nth eligible line and ``min_gap_sec`` has passed."""
        s = self.settings
        trig = self._trigger("chat", s)
        # paid lines are read through their alert (the "paid" trigger), never twice
        if trig is None or getattr(event, "from_core", False) or getattr(event, "is_paid", False):
            return False
        raw = str(getattr(event, "message", "") or "")
        if raw.startswith(self.prefix() or "!"):
            return False
        user = event.user
        if not (self.is_admin(user) or who_ok(user, trig["who"])) or self.is_blocked(who_key(user.platform, user.username)):
            return False
        self._chat_seen += 1
        if (self._chat_seen - 1) % trig["every_nth"]:
            return False
        now = time.time()
        if trig["min_gap_sec"] and now - self._chat_last < trig["min_gap_sec"]:
            return False
        flt = self.text_filter(s)
        spoken = flt.clean_name(user.display_name or user.username)
        message, _ = strip_emotes(raw, getattr(event, "emotes", None))
        text, why = flt.clean(fill(trig["template"], name=spoken, message=message))
        if why:
            if why == "blocked word":
                self._log("chat", message, "skipped", why, name=spoken)
            return False
        self._chat_last = now
        return self._queue_now(text, "chat", voice=trig["voice"],
                               platform=getattr(user.platform, "value", user.platform) or "", name=spoken,
                               who=who_key(user.platform, user.username)) is not None

    def on_highlight(self, item: dict) -> bool:
        """A Highlighted message reached the screen (HighlightBoard.on_shown, main.py)."""
        s = self.settings
        trig = self._trigger("highlight", s)
        if trig is None:
            return False
        user = item.get("user") or {}
        hwho = who_key(item.get("platform"), user.get("username"))
        if self.is_blocked(hwho):
            return False
        flt = self.text_filter(s)
        spoken = flt.clean_name(user.get("display_name") or user.get("username") or "")
        message, _ = strip_emotes(str(item.get("message") or ""), item.get("emotes"))
        text, why = flt.clean(fill(trig["template"], name=spoken, message=message))
        if why:
            self._log("highlight", message, "skipped", why, name=spoken)
            return False
        return self._queue_now(text, "highlight", voice=trig["voice"], platform=str(item.get("platform") or ""),
                               name=spoken, who=hwho) is not None

    async def say_plugin(self, plugin_id: str, text: str, voice: str = "") -> bool:
        """A game plugin asks Core to say something (PluginContext.say). Read when the plugins
        trigger is on; ``voice`` "" = the trigger's voice, then the main voice."""
        s = self.settings
        trig = self._trigger("plugins", s)
        if trig is None:
            return False
        clean, why = self.text_filter(s).clean(str(text or ""))
        trigger = f"plugin: {plugin_id}"
        if why:
            self._log(trigger, str(text or ""), "skipped", why)
            return False
        return await self.enqueue(clean, trigger, voice=" ".join(str(voice or "").split())[:100] or trig["voice"]) is not None

    # ── settings page tools ──

    async def say_test(self, text: str, voice: str = "") -> Tuple[bool, str]:
        """"Send to overlay": a line through the filters and the real queue (no trigger needed,
        but TTS must be on). Returns (queued, why not)."""
        s = self.settings
        if not s["enabled"]:
            return False, "Text-to-speech is off: switch it on first."
        clean, why = self.text_filter(s).clean(text)
        if why:
            return False, f"Not read: {why}."
        job = await self.enqueue(clean, "test", voice=voice)
        return (job is not None), ("" if job else "The queue is full.")

    def filter_test(self, text: str, name: str = "") -> Dict[str, str]:
        """The blocked-words test box: what ``text`` (and ``name``) would be read as."""
        flt = self.text_filter()
        message, _ = strip_emotes(text)
        out, why = flt.clean(message)
        return {"text": out, "why": why, "name": flt.clean_name(name) if name else ""}

    async def test_audio(self, text: str, voice: str = "") -> Tuple[bytes, str]:
        """"Test voice": the audio for one line, straight back to the dashboard (no overlay, no
        queue, no filters). Raises TtsError. A success also clears a "down" state."""
        s = self.settings
        audio, ctype, seconds = await self._synth(s, text, voice or s["voice"], count=False)
        self._log("test voice", text, "played", voice=voice or s["voice"], seconds=seconds)
        return audio, ctype

    async def check(self) -> Dict[str, Any]:
        """"Check connection": one short line, timed, plus the server's voice list when it has one."""
        s = self.settings
        out: Dict[str, Any] = {"ok": False, "seconds": 0.0, "format": s["server"]["format"],
                               "voices": [], "url": speech_url(s["server"]["url"]), "error": ""}
        if not s["server"]["url"]:
            out["error"] = "Type your TTS server's address first."
            return out
        try:
            audio, ctype, seconds = await self._synth(s, CHECK_TEXT, s["voice"], count=False)
            out.update(ok=True, seconds=round(seconds, 2), content_type=ctype, bytes=len(audio))
        except TtsError as e:
            out["error"] = str(e)
        out["voices"] = await self.list_voices(s)
        return out

    async def list_voices(self, s: Optional[dict] = None) -> List[str]:
        """Voice names from GET /v1/audio/voices, for servers that have it ([] otherwise)."""
        s = s or self.settings
        url = voices_url(s["server"]["url"])
        if not url:
            return []
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self.transport) as client:
                res = await client.get(url, headers=self._headers(s))
            if res.status_code != 200:
                return []
            data = res.json()
        except Exception:
            return []
        items = data.get("voices") if isinstance(data, dict) else data
        names = []
        for v in items if isinstance(items, list) else []:
            if isinstance(v, str):
                names.append(v)
            elif isinstance(v, dict):
                n = v.get("id") or v.get("name") or v.get("voice_id")
                if n:
                    names.append(str(n))
        return sorted(set(n[:100] for n in names))[:500]

    async def skip(self) -> None:
        """Stop the line playing now; the next one goes on."""
        await self._send({"type": "tts_control", "data": {"action": "skip"}})
        self._log("skip", "", "skipped", "Skip pressed")

    async def clear(self) -> int:
        """Stop the line playing and drop every line waiting (here and in the overlays). Points
        for dropped !tts lines are given back. Returns how many were dropped."""
        dropped = list(self.pending)
        self.pending.clear()
        for job in dropped:
            if job.alert_id:
                await self._send({"type": "tts_skip", "data": {"alert_id": job.alert_id}})
            await self._refund(job, "queue cleared")
        await self._send({"type": "tts_control", "data": {"action": "clear"}})
        self._log("clear", "", "skipped", f"Clear pressed ({len(dropped)} waiting dropped)")
        return len(dropped)

    async def replay(self, missed_id: Optional[int] = None) -> int:
        """Put missed lines back in the queue (one by id, or all with None). Returns how many."""
        picked = [m for m in self.missed if missed_id is None or m["id"] == missed_id]
        count = 0
        for m in picked:
            job = await self.enqueue(m["text"], "replay", voice=m["voice"], platform=m["platform"], name=m["name"])
            if job is None:
                break
            self.missed.remove(m)
            count += 1
        return count

    def forget_missed(self, missed_id: Optional[int] = None) -> int:
        """Drop missed lines (one by id, or all with None). Returns how many."""
        before = len(self.missed)
        self.missed = [m for m in self.missed if missed_id is not None and m["id"] != missed_id]
        return before - len(self.missed)

    # ── Live card controls and blocked chatters (work list item 19) ──

    def is_quiet(self) -> bool:
        """True while "off for N minutes" runs."""
        return self.quiet_until > time.time()

    def set_paused(self, on: bool) -> None:
        """Pause: nothing new starts; the waiting lines stay in line until Resume."""
        self.paused = bool(on)
        if not on:
            self._wake.set()

    async def quiet_for(self, minutes: float) -> int:
        """Read aloud off for ``minutes`` (0 = back on now). New lines aren't read meanwhile and the
        waiting ones are dropped (paid / !tts to the missed list, points given back). Returns how
        many waiting lines were dropped."""
        minutes = max(0.0, min(float(minutes or 0), QUIET_MAX_MIN))
        self.quiet_until = time.time() + minutes * 60 if minutes else 0.0
        dropped = 0
        if minutes:
            for job in list(self.pending):
                self.pending.remove(job)
                await self._give_up(job, "read aloud off for a while")
                dropped += 1
            self._log("quiet", "", "skipped", f"Off for {minutes:g} min ({dropped} waiting dropped)")
        else:
            self._wake.set()
        return dropped

    async def drop(self, job_id: int) -> bool:
        """Take one waiting line out (the Live card's ✕). Its points are given back."""
        for job in list(self.pending):
            if job.id == job_id:
                self.pending.remove(job)
                await self._give_up(job, "removed")
                self._log(job.trigger, job.text, "skipped", "removed from the line", job.voice, name=job.name)
                return True
        return False

    def _blocked_file(self) -> Path:
        return self.dir / "blocked_people.json"

    def _load_blocked(self) -> Dict[str, Dict[str, Any]]:
        """The saved blocks ("day" and "forever"); ones that ran out are left behind."""
        try:
            raw = json.loads(self._blocked_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        now = time.time()
        out = {}
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            if isinstance(v, dict) and (not v.get("until") or float(v["until"]) > now):
                out[str(k)[:120]] = v
        return out

    def _save_blocked(self) -> None:
        keep = {k: v for k, v in self.blocked_people.items() if v.get("for") != "stream"}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._blocked_file().write_text(json.dumps(keep, indent=1), encoding="utf-8")
        except OSError:
            log.warning("couldn't save the blocked chatters list")

    def is_blocked(self, key: str) -> bool:
        """True while that chatter (who_key) is blocked from being read aloud."""
        b = self.blocked_people.get(key)
        if not b:
            return False
        if b.get("until") and float(b["until"]) <= time.time():
            self.blocked_people.pop(key, None)
            return False
        return True

    def block(self, platform: str, name: str, for_: str = "stream") -> Optional[Dict[str, Any]]:
        """Block a chatter from read aloud for this stream / a day / for good. Their waiting lines
        go too. Called from the Blocked tab, the Live card and Stream Rooms' people menu
        ("tts_block" packet). Returns the entry, or None for an empty name."""
        name = str(name or "").strip().lstrip("@")[:60]
        if not name:
            return None
        for_ = for_ if for_ in BLOCK_FOR else "stream"
        key = who_key(platform, name)
        now = time.time()
        entry = {"platform": str(platform or "")[:20].lower(), "name": name, "for": for_,
                 "until": now + BLOCK_FOR[for_] if BLOCK_FOR[for_] else 0, "at": now}
        self.blocked_people[key] = entry
        while len(self.blocked_people) > BLOCK_MAX:
            self.blocked_people.pop(next(iter(self.blocked_people)))
        for job in list(self.pending):
            if job.who == key:
                self.pending.remove(job)
        self._save_blocked()
        self._log("block", "", "skipped", f"Blocked {name} ({for_})", name=name)
        return entry

    def unblock(self, key: str) -> bool:
        gone = self.blocked_people.pop(str(key or ""), None) is not None
        if gone:
            self._save_blocked()
        return gone

    def blocked_list(self) -> List[Dict[str, Any]]:
        """For the Blocked tab: [{key, platform, name, for, until, at}], newest first."""
        out = [{"key": k, **v} for k, v in self.blocked_people.items() if self.is_blocked(k)]
        return sorted(out, key=lambda b: -float(b.get("at") or 0))

    def set_pretend_down(self, on: bool) -> None:
        """The settings page's "Pretend the server is down" switch (not saved). Turning it off lets
        the next check bring the server back."""
        self.pretend_down = bool(on)
        if not on and self.down:
            self.last_try_at = 0.0      # check again at once
            self._wake.set()

    def status(self) -> Dict[str, Any]:
        """For the status lights (settings page, Live controls card, top bar)."""
        s = self.settings
        if not s["enabled"]:
            state = "off"
        elif not s["server"]["url"]:
            state = "no_server"
        elif self.down:
            state = "down"
        elif self.last_ok_at and self.fails == 0:
            state = "ok"
        elif self.fails:
            state = "trouble"
        else:
            state = "unknown"
        return {"state": state, "enabled": s["enabled"], "fails": self.fails, "down": self.down,
                "down_since": self.down_since, "last_error": self.last_error, "last_ok_at": self.last_ok_at,
                "last_seconds": self.last_seconds, "pretend_down": self.pretend_down,
                "queue_len": len(self.pending), "missed": len(self.missed),
                "paused": self.paused, "quiet_until": self.quiet_until if self.is_quiet() else 0,
                "now": self.now if self.now and time.time() - self.now["at"] < self.now["sec"] + 2 else None,
                "next": [{"id": j.id, "text": j.text[:160], "name": j.name, "trigger": j.trigger}
                         for j in list(self.pending)[:5]],
                "blocked": len(self.blocked_people)}

    # ── talking to the server ──

    @staticmethod
    def _headers(s: dict) -> Dict[str, str]:
        key = s["server"]["api_key"]
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def _post(self, s: dict, base: str, text: str, voice: str) -> Tuple[bytes, str]:
        """One POST /v1/audio/speech to one address. Raises TtsError in plain words."""
        url = speech_url(base)
        srv = s["server"]
        body = {"model": srv["model"], "input": text, "voice": voice or s["voice"],
                "response_format": srv["format"], "speed": s["speed"]}
        try:
            async with httpx.AsyncClient(timeout=float(srv["timeout_sec"]), transport=self.transport) as client:
                res = await client.post(url, json=body, headers=self._headers(s))
        except httpx.TimeoutException:
            raise TtsError(f"{_host(url)} didn't answer within {srv['timeout_sec']} s")
        except httpx.HTTPError as e:
            raise TtsError(f"Can't reach {_host(url)} ({type(e).__name__})")
        ctype = (res.headers.get("content-type") or "").split(";")[0].strip().lower()
        if res.status_code in (401, 403):
            raise TtsError(f"{_host(url)} refused the API key (HTTP {res.status_code})")
        if res.status_code == 404:
            raise TtsError(f"{_host(url)} has no /v1/audio/speech (HTTP 404): check the address")
        if res.status_code >= 400 or ctype in ("application/json", "text/html", "text/plain"):
            detail = ""
            try:
                data = res.json()
                d = data.get("detail") or data.get("error") or data.get("message") if isinstance(data, dict) else data
                if isinstance(d, dict):
                    d = d.get("message") or d.get("msg") or str(d)
                detail = str(d or "")
            except Exception:
                detail = res.text if ctype.startswith("text/plain") else ""
            detail = " ".join(detail.split())[:200]
            raise TtsError(f"{_host(url)} said HTTP {res.status_code}" + (f": {detail}" if detail else "")
                           + ("" if res.status_code >= 400 else " instead of audio"))
        if not res.content:
            raise TtsError(f"{_host(url)} sent no audio")
        return res.content, ctype or FORMATS[srv["format"]][1]

    async def _synth(self, s: dict, text: str, voice: str, count: bool = True) -> Tuple[bytes, str, float]:
        """Audio for ``text``: the main address, then the backup. Updates the server state.
        ``count`` = failures count toward "down" (False for the settings page's own tests)."""
        start = time.monotonic()
        self.last_try_at = time.time()
        try:
            if self.pretend_down:
                raise TtsError("Pretending the server is down (switch on the settings page)")
            if not s["server"]["url"]:
                raise TtsError("No TTS server address set")
            errors = []
            for base in (s["server"]["url"], s["server"]["backup_url"]):
                if not base:
                    continue
                try:
                    audio, ctype = await self._post(s, base, text, voice)
                    break
                except TtsError as e:
                    errors.append(str(e))
            else:
                raise TtsError("; ".join(errors))
        except TtsError as e:
            self.last_error = str(e)
            if count:
                self.fails += 1
                if self.fails >= FAIL_LIMIT and not self.down:
                    self.down = True
                    self.down_since = time.time()
                    log.warning("TTS server marked down after %s failures: %s", self.fails, e)
                    self._note("error", f"Text-to-speech server isn't answering, lines are skipped for now: {e}")
            raise
        seconds = time.monotonic() - start
        self.last_seconds = seconds
        self.last_ok_at = time.time()
        self.fails = 0
        if self.down:
            self.down = False
            log.info("TTS server is back")
            self._note("alert", "Text-to-speech server is back")
        return audio, ctype, seconds

    def _note(self, kind: str, text: str) -> None:
        if callable(self.note):
            try:
                self.note(kind, text)
            except Exception:
                log.exception("tts note failed")

    async def _send(self, payload: dict) -> None:
        if callable(self.broadcast):
            try:
                await self.broadcast(payload)
            except Exception:
                log.exception("tts broadcast failed")

    def _save(self, audio: bytes, ctype: str, fmt: str) -> str:
        """Write the audio under data/tts/ and return its file name; old files are deleted."""
        ext = CTYPE_EXT.get(ctype) or FORMATS[fmt][0]
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{int(time.time() * 1000)}-{next(self._files)}.{ext}"
        (self.dir / name).write_bytes(audio)
        try:
            files = sorted((p for p in self.dir.iterdir() if FILE_RE.match(p.name)), key=lambda p: p.stat().st_mtime)
            for old in files[:-KEEP_FILES]:
                old.unlink(missing_ok=True)
        except OSError:
            log.debug("tts clean-up failed", exc_info=True)
        return name

    def file_path(self, name: str) -> Optional[Path]:
        """A saved audio file for /tts/<name> (api/server.py), or None."""
        if not FILE_RE.match(name or ""):
            return None
        path = self.dir / name
        return path if path.is_file() else None

    async def process(self, job: Job) -> bool:
        """Read one job: ask the server, save the audio, tell the overlays. True when sent."""
        s = self.settings
        if not s["enabled"]:
            await self._give_up(job, "text-to-speech is off")
            return False
        if self.down:
            self._log(job.trigger, job.text, "failed", "server down", job.voice, name=job.name)
            await self._give_up(job, "server down")
            return False
        try:
            audio, ctype, seconds = await self._synth(s, job.text, job.voice)
        except TtsError as e:
            self._log(job.trigger, job.text, "failed", str(e), job.voice, name=job.name)
            await self._give_up(job, str(e))
            return False
        try:
            name = self._save(audio, ctype, s["server"]["format"])
        except OSError as e:
            self._log(job.trigger, job.text, "failed", f"couldn't save the audio: {e}", job.voice, name=job.name)
            await self._give_up(job, "couldn't save the audio")
            return False
        await self._send({"type": "tts", "data": {"id": job.id, "url": f"/tts/{name}", "alert_id": job.alert_id,
                                                  "platform": job.platform, "volume": s["volume"],
                                                  "trigger": job.trigger}})
        # roughly how long it plays (the audio's own length isn't read): for the Live card's
        # "Reading now" and the chatter's glowing silhouette in Stream Rooms ("tts_speaking")
        sec = max(GLOW_MIN_SEC, min(GLOW_MAX_SEC, len(job.text) * GLOW_SEC_PER_CHAR / max(s["speed"], 0.5)))
        self.now = {"id": job.id, "text": job.text[:200], "name": job.name, "trigger": job.trigger,
                    "at": time.time(), "sec": round(sec, 1)}
        if job.who:
            plat, _, uname = job.who.partition(":")
            await self._send({"type": "tts_speaking", "data": {"platform": plat, "username": uname,
                                                               "seconds": round(sec, 1)}})
        self._log(job.trigger, job.text, "played", voice=job.voice, seconds=seconds, name=job.name)
        return True

    async def recheck(self) -> bool:
        """While down: one short line to see whether the server is back."""
        try:
            await self._synth(self.settings, CHECK_TEXT, self.settings["voice"], count=False)
            return True
        except TtsError:
            return False

    async def run(self, stop: Optional[asyncio.Event] = None) -> None:
        """The worker (main.py starts it): one line at a time, oldest first. While the server is
        down it re-checks every RECHECK_SEC seconds."""
        while not (stop and stop.is_set()):
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self.down and self.settings["enabled"] and time.time() - self.last_try_at >= RECHECK_SEC:
                await self.recheck()
            while self.pending and not self.paused and not (stop and stop.is_set()):
                job = self.pending.popleft()
                try:
                    await self.process(job)
                except Exception:
                    log.exception("tts line failed")
