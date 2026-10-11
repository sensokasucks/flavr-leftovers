"""
Custom chat flags: the streamer's own flags next to the built-in red flag.

Each flag has a name, its own phrases (matched like red flag phrases: case-insensitive,
whole words, ``*`` = any letters) and the things it does when a chatter says one. A chatter
who says one goes on that flag's list (SQLite table ``chat_flagged``); the list is on the
Red flags page and the flag's name shows next to their lines in Chat history.

Config (``red_flags.custom:`` in config.yaml, People → Red flags)::

  - id: giveaway            made from the name the first time; stays the same after
    name: Giveaway entry
    enabled: true
    phrases: ["enter me", "giveaway*"]
    skip_mods: true         moderators and the streamer never get this flag from a phrase
    every_time: false       false = the actions run once, when a chatter first gets the flag;
                            true = on every matching line (at most once per cooldown_sec each)
    cooldown_sec: 30
    log: true               save every line they write in the chat log, even with Save chat
                            history off or set to red-flagged chatters only
    hide: false             red-flag them too (kept off every overlay and out of Stream Rooms)
    alert: false            show an alert (kind "flag") with alert_text
    alert_text: "{name} said {phrase}!"
    reply: ""               answer with this (a Stream Core line on the chat / replies overlays,
                            like command answers; empty = no answer)
    points: 0               give (or, below 0, take) this many points
    reaction: ""            play this reaction (its id on the Reactions page), free
    notify: true            tell game plugins (``on_flag``) and overlays (``chat_flag``)

Placeholders in alert_text / reply: {name} {user} {phrase} {flag} {message} {platform}.
What the actions do is in main.py (``StreamCore._flag_actions``); this file only matches and
keeps the lists.
"""

from __future__ import annotations

import copy
import logging
import re
import time
from typing import Any, Iterable, Optional

from core.models import ChatEvent
from core.red_flags import (MAX_PAST_PEOPLE, PAST_EXAMPLES, compile_phrase, normalize,
                            parse_phrases)

log = logging.getLogger("core.chat_flags")

MAX_FLAGS = 50
MAX_NAME_LEN = 40
MAX_TEXT_LEN = 300
MAX_POINTS = 1_000_000

# what a flag can do (the booleans), in the order the dashboard shows them
ACTION_KEYS = ("log", "hide", "alert", "notify")

DEFAULT_FLAG: dict[str, Any] = {
    "id": "",
    "name": "",
    "enabled": True,
    "phrases": [],
    "skip_mods": True,
    "every_time": False,
    "cooldown_sec": 30,
    "log": True,
    "hide": False,
    "alert": False,
    "alert_text": "{name} said {phrase}!",
    "reply": "",
    "points": 0,
    "reaction": "",
    "notify": True,
}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")
    return s[:32] or "flag"


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def normalize_flag(raw: Any, taken: set[str]) -> Optional[dict]:
    """One flag from the dashboard or config, every key filled in; None = no name."""
    if not isinstance(raw, dict):
        return None
    name = " ".join(str(raw.get("name") or "").split())[:MAX_NAME_LEN]
    if not name:
        return None
    flag = dict(DEFAULT_FLAG)
    flag["name"] = name
    fid = slug(str(raw.get("id") or "") or name)
    if fid == "red":            # the built-in red flag's name in the API
        fid = "red-1"
    base, n = fid, 2
    while fid in taken:
        fid = f"{base}-{n}"
        n += 1
    flag["id"] = fid
    for key in ("enabled", "skip_mods", "every_time", "log", "hide", "alert", "notify"):
        if key in raw:
            flag[key] = bool(raw.get(key))
    flag["phrases"] = parse_phrases(raw.get("phrases") or [])
    flag["cooldown_sec"] = _int(raw.get("cooldown_sec", 30), 30, 0, 86400)
    flag["points"] = _int(raw.get("points", 0), 0, -MAX_POINTS, MAX_POINTS)
    for key in ("alert_text", "reply"):
        if key in raw:
            flag[key] = " ".join(str(raw.get(key) or "").split())[:MAX_TEXT_LEN]
    flag["reaction"] = str(raw.get("reaction") or "").strip().lower()[:60]
    return flag


def normalize_custom(raw: Any) -> list[dict]:
    """``red_flags.custom`` as a clean list (names required, ids unique)."""
    out: list[dict] = []
    taken: set[str] = set()
    for item in list(raw or [])[:MAX_FLAGS] if isinstance(raw, list) else []:
        flag = normalize_flag(item, taken)
        if flag is None:
            continue
        taken.add(flag["id"])
        out.append(flag)
    return out


class Flag:
    """One custom flag, its phrases compiled."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg["name"]
        self._patterns: list[tuple[str, re.Pattern]] = []
        for phrase in cfg["phrases"]:
            pat = compile_phrase(phrase)
            if pat is not None:
                self._patterns.append((phrase, pat))
        self._any = re.compile("|".join(f"(?:{p.pattern})" for _, p in self._patterns)) \
            if self._patterns else None

    def __getattr__(self, key: str) -> Any:
        try:
            return self.cfg[key]
        except KeyError:
            raise AttributeError(key) from None

    def match(self, text: str, norm: Optional[str] = None) -> Optional[str]:
        if self._any is None or not text:
            return None
        norm = normalize(text) if norm is None else norm
        if not self._any.search(norm):
            return None
        for phrase, pat in self._patterns:
            if pat.search(norm):
                return phrase
        return None

    @property
    def matches_anything(self) -> bool:
        return self._any is not None


class ChatFlags:
    def __init__(self, store, red_flags, custom: Any = None):
        self.store = store
        self.red_flags = red_flags        # its mod / staff exemption is shared
        self.flags: list[Flag] = []
        self._raw: Any = object()
        # flag id -> (platform, user id) / (platform, lower-case name)
        self._ids: dict[str, set[tuple[str, str]]] = {}
        self._names: dict[str, set[tuple[str, str]]] = {}
        self._last: dict[tuple[str, str], float] = {}     # (flag, chatter) -> last action time
        self.configure(custom)
        self.reload()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def configure(self, custom: Any) -> None:
        """Follow ``red_flags.custom`` (cheap when nothing changed)."""
        if custom == self._raw:
            return
        self._raw = copy.deepcopy(custom)
        self.flags = [Flag(c) for c in normalize_custom(custom)]

    def get(self, flag_id: str) -> Optional[Flag]:
        return next((f for f in self.flags if f.id == flag_id), None)

    def info(self) -> list[dict]:
        return [dict(f.cfg) for f in self.flags]

    # ------------------------------------------------------------------
    # The lists
    # ------------------------------------------------------------------

    def reload(self) -> None:
        ids: dict[str, set] = {}
        names: dict[str, set] = {}
        for row in self.store.list_chat_flagged_sync():
            fid = str(row.get("flag") or "")
            plat = str(row.get("platform") or "")
            if row.get("platform_user_id"):
                ids.setdefault(fid, set()).add((plat, str(row["platform_user_id"])))
            for n in (row.get("username"), row.get("display_name")):
                if n:
                    names.setdefault(fid, set()).add((plat, normalize(n)))
        self._ids, self._names = ids, names

    def on_list(self, flag_id: str, platform: str, user_id: str = "", *names: str) -> bool:
        platform = str(platform or "")
        if user_id and (platform, str(user_id)) in self._ids.get(flag_id, ()):
            return True
        known = self._names.get(flag_id, ())
        for n in names:
            key = normalize(n)
            if key and ((platform, key) in known or ("", key) in known):
                return True
        return False

    def flags_for(self, platform: str, user_id: str = "", *names: str) -> list[str]:
        """Ids of the (current) flags this chatter is on."""
        return [f.id for f in self.flags if self.on_list(f.id, platform, user_id, *names)]

    def keeps_log(self, platform: str, user_id: str = "", *names: str) -> bool:
        """On a switched-on flag that saves their chat?"""
        return any(f.enabled and f.log and self.on_list(f.id, platform, user_id, *names) for f in self.flags)

    # ------------------------------------------------------------------
    # Live chat
    # ------------------------------------------------------------------

    async def check(self, event: ChatEvent) -> list[dict]:
        """Every flag this line sets off: ``[{"flag": Flag, "phrase", "first", "row"}]``.
        ``first`` = the chatter just went on the list. A chatter already on it only counts
        again for a flag set to ``every_time`` (and not within its cooldown)."""
        hits: list[dict] = []
        text = event.message or ""
        live = [f for f in self.flags if f.enabled and f.matches_anything]
        if not live or not text:
            return hits
        user = event.user
        plat = event.platform.value
        uid = str(user.id or "")
        staff = bool(user.is_mod or "broadcaster" in [str(b).lower() for b in user.badges or []])
        norm = normalize(text)
        now = time.time()
        for flag in live:
            if flag.skip_mods and staff:
                continue
            phrase = flag.match(text, norm)
            if phrase is None:
                continue
            first = not self.on_list(flag.id, plat, uid, user.username, user.display_name)
            row = await self.flag(flag.id, plat, uid, user.username, user.display_name,
                                  phrase=phrase, message=text, source="phrase")
            key = (flag.id, f"{plat}:{uid or normalize(user.username)}")
            if not first:
                if not flag.every_time or now - self._last.get(key, 0) < flag.cooldown_sec:
                    continue
            self._last[key] = now
            if len(self._last) > 50_000:
                self._last.clear()
            log.info("Flag %s: [%s] %s said %r", flag.name, plat, user.display_name or user.username, phrase)
            hits.append({"flag": flag, "phrase": phrase, "first": first, "row": row})
        return hits

    # ------------------------------------------------------------------
    # Check past chat
    # ------------------------------------------------------------------

    def scan_past_sync(self, flag_id: str, rows: Iterable[dict], max_people: int = MAX_PAST_PEOPLE) -> dict:
        """Like ``RedFlags.scan_past_sync``, for one custom flag: who said one of its phrases
        before (chatters already on its list are left out, mods too when it skips them)."""
        flag = self.get(flag_id)
        if flag is None or not flag.matches_anything:
            return {"scanned": 0, "people": [], "more": False}
        scanned = 0
        people: dict[tuple[str, str], dict] = {}
        more = False
        exempt: dict[tuple[str, str, str], bool] = {}
        for row in rows:
            scanned += 1
            text = str(row.get("message") or "")
            phrase = flag.match(text) if text else None
            if phrase is None:
                continue
            plat = str(row.get("platform") or "")
            uid = str(row.get("platform_user_id") or "")
            username = str(row.get("username") or "")
            display = str(row.get("display_name") or "")
            if self.on_list(flag.id, plat, uid, username, display):
                continue
            if flag.skip_mods:
                ek = (plat, uid, username)
                if ek not in exempt:
                    exempt[ek] = self.red_flags.is_exempt(plat, uid, username, display)
                if exempt[ek]:
                    continue
            key = (plat, uid or "name:" + normalize(username or display))
            person = people.get(key)
            if person is None:
                if len(people) >= max_people:
                    more = True
                    continue
                person = people[key] = {
                    "platform": plat, "platform_user_id": uid,
                    "username": username, "display_name": display or username,
                    "phrase": phrase, "message": text[:500], "timestamp": row.get("timestamp"),
                    "count": 0, "examples": [],
                }
            person["count"] += 1
            if len(person["examples"]) < PAST_EXAMPLES:
                person["examples"].append({"message": text[:300], "timestamp": row.get("timestamp")})
        return {"scanned": scanned, "people": list(people.values()), "more": more}

    async def scan_past(self, flag_id: str) -> dict:
        def _scan():
            return self.scan_past_sync(flag_id, self.store.iter_chat_sync())
        return await self.store._run(_scan)

    # ------------------------------------------------------------------
    # Changes
    # ------------------------------------------------------------------

    async def flag(self, flag_id: str, platform: str, user_id: str, username: str, display_name: str = "",
                   phrase: str = "", message: str = "", source: str = "manual") -> dict:
        row = await self.store.add_chat_flag(
            flag=flag_id, platform=str(platform or ""), platform_user_id=str(user_id or ""),
            username=normalize(username).strip(), display_name=str(display_name or username or "").strip(),
            phrase=phrase, message=message, source=source,
        )
        if row.get("hits", 1) <= 1:
            await self.store._run(self.reload)
        return row

    async def unflag(self, row_id: int) -> Optional[dict]:
        row = await self.store.remove_chat_flag(int(row_id))
        await self.store._run(self.reload)
        return row

    async def forget(self, flag_ids: Iterable[str]) -> int:
        """A flag was deleted: clear its list."""
        gone = 0
        for fid in flag_ids:
            gone += await self.store.clear_chat_flag(fid)
        if gone:
            await self.store._run(self.reload)
        return gone

    async def list(self) -> list[dict]:
        return await self.store._run(self.store.list_chat_flagged_sync)
