"""
Red flags: phrases that mark a chatter, and the list of marked chatters.

A chat line containing one of ``red_flags.phrases`` puts its sender on the red-flag list
(SQLite table ``red_flagged``, next to the chat log). From then on Core keeps that person
off every overlay and out of Stream Rooms: their chat is not broadcast, they get no
reactions, commands, points, credits or alerts. Their messages are still saved in the
chat log (when it is on) so the Chat history tab can show what they wrote.

Config (``red_flags:`` in config.yaml, its own card on the Chat history tab)::

  enabled: true      off = nobody is hidden and nobody new is flagged (the list is kept)
  skip_mods: true    moderators and the streamer never get flagged by a phrase
  phrases: []        one per entry, case-insensitive, whole words; ``*`` = any letters
                     ("scam*" matches "scammer"); spaces match any run of spaces

The streamer can also flag a name by hand and unflag anyone on the dashboard, and
"Check past chat" runs the phrases over the saved chat log (``scan_past_sync``) so chatters
who said one before it was added can be flagged after a look at the list.
"""

from __future__ import annotations

import copy
import logging
import re
import unicodedata
from typing import Any, Callable, Iterable, Optional

from core.models import ChatEvent

log = logging.getLogger("core.red_flags")

MAX_PHRASES = 500
MAX_PHRASE_LEN = 120
MAX_PAST_PEOPLE = 500     # "Check past chat" lists at most this many chatters
PAST_EXAMPLES = 3         # matching lines kept per chatter for the list

# zero-width and soft-hyphen characters people slip into a word to get past a filter
_INVISIBLE = dict.fromkeys(map(ord, "­᠎​‌‍⁠﻿"), None)


def normalize(text: str) -> str:
    """Lower-case, fold look-alike letters (fullwidth, ligatures) and drop invisible characters."""
    text = unicodedata.normalize("NFKC", str(text or "")).translate(_INVISIBLE)
    return text.casefold()


def parse_phrases(raw: Any) -> list[str]:
    """Phrases from a list or one-per-line text: trimmed, no blanks, no repeats (any case)."""
    items = raw.splitlines() if isinstance(raw, str) else list(raw or [])
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        phrase = " ".join(str(item or "").split())[:MAX_PHRASE_LEN]
        key = normalize(phrase)
        if not phrase or key.strip("*") == "" or key in seen:
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) >= MAX_PHRASES:
            break
    return out


def compile_phrase(phrase: str) -> Optional[re.Pattern]:
    """'free  vbucks' -> whole-word, case-insensitive pattern; '*' stands for any letters."""
    words = normalize(phrase).split()
    if not words:
        return None
    parts = []
    for word in words:
        parts.append(r"\w*".join(re.escape(bit) for bit in word.split("*")))
    body = r"\s+".join(parts)
    # whole words only, so "ass" does not catch "class"; a phrase starting or ending in a
    # symbol ("$$$", "@everyone") has no word edge there, so only letters/digits get the guard
    start = r"(?<!\w)" if re.match(r"\w|\*", words[0]) else ""
    end = r"(?!\w)" if re.search(r"(\w|\*)$", words[-1]) else ""
    return re.compile(start + body + end)


class RedFlags:
    def __init__(self, store, cfg: Optional[dict] = None):
        self.store = store
        self.enabled = True
        self.skip_mods = True
        self.phrases: list[str] = []
        self._patterns: list[tuple[str, re.Pattern]] = []
        self._any: Optional[re.Pattern] = None       # every phrase in one pattern
        self._cfg: Any = object()
        self._ids: set[tuple[str, str]] = set()      # (platform, platform user id)
        self._names: set[tuple[str, str]] = set()    # (platform or "", lower-case name)
        # mods / the streamer seen in live chat (the chat log does not keep badges), so
        # "Check past chat" can skip them too; ``staff`` (main.py) adds Core's own mod list
        self._seen_mods: set[tuple[str, str]] = set()
        self.staff: Optional[Callable[[str, str, str], bool]] = None
        self.configure(cfg)
        self.reload()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def configure(self, cfg: Optional[dict]) -> None:
        """Follow ``red_flags:`` in config (cheap when nothing changed)."""
        cfg = cfg if isinstance(cfg, dict) else {}
        if cfg == self._cfg:
            return
        self._cfg = copy.deepcopy(cfg)
        self.enabled = bool(cfg.get("enabled", True))
        self.skip_mods = bool(cfg.get("skip_mods", True))
        self.phrases = parse_phrases(cfg.get("phrases") or [])
        self._patterns = []
        for phrase in self.phrases:
            pat = compile_phrase(phrase)
            if pat is not None:
                self._patterns.append((phrase, pat))
        # one search per chat line, however long the list; which phrase it was is only
        # worked out on a hit
        self._any = re.compile("|".join(f"(?:{pat.pattern})" for _, pat in self._patterns)) \
            if self._patterns else None

    def match(self, text: str) -> Optional[str]:
        """The first phrase found in ``text``, else None."""
        if self._any is None or not text:
            return None
        norm = normalize(text)
        if not self._any.search(norm):
            return None
        for phrase, pat in self._patterns:
            if pat.search(norm):
                return phrase
        return None

    # ------------------------------------------------------------------
    # The list
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Rebuild the in-memory lookup from the database."""
        ids: set[tuple[str, str]] = set()
        names: set[tuple[str, str]] = set()
        for row in self.store.list_red_flagged_sync():
            plat = str(row.get("platform") or "")
            if row.get("platform_user_id"):
                ids.add((plat, str(row["platform_user_id"])))
            for n in (row.get("username"), row.get("display_name")):
                if n:
                    names.add((plat, normalize(n)))
        self._ids, self._names = ids, names

    def is_flagged(self, platform: str, user_id: str = "", *names: str) -> bool:
        """On the list (by account id, or by name on that platform / any platform)? Ignores ``enabled``."""
        platform = str(platform or "")
        if user_id and (platform, str(user_id)) in self._ids:
            return True
        for n in names:
            key = normalize(n)
            if key and ((platform, key) in self._names or ("", key) in self._names):
                return True
        return False

    def hides(self, platform: str, user_id: str = "", *names: str) -> bool:
        """Should this chatter be kept off overlays right now?"""
        return self.enabled and self.is_flagged(platform, user_id, *names)

    async def check(self, event: ChatEvent) -> Optional[dict]:
        """None = show this chat line as usual. Otherwise ``{"new": bool, "flag": row}``:
        the sender was already flagged (``new`` False) or this line just flagged them."""
        if not self.enabled:
            return None
        user = event.user
        plat = event.platform.value
        if self.is_flagged(plat, str(user.id or ""), user.username, user.display_name):
            return {"new": False, "flag": None}
        if self.skip_mods and (user.is_mod or "broadcaster" in [str(b).lower() for b in user.badges or []]):
            self._note_mod(plat, str(user.id or ""), user.username, user.display_name)
            return None
        phrase = self.match(event.message or "")
        if phrase is None:
            return None
        row = await self.flag(plat, str(user.id or ""), user.username, user.display_name,
                              phrase=phrase, message=event.message or "", source="phrase")
        log.info("Red flag: [%s] %s said %r", plat, user.display_name or user.username, phrase)
        return {"new": True, "flag": row}

    def _note_mod(self, platform: str, user_id: str, *names: str) -> None:
        if user_id:
            self._seen_mods.add((platform, "id:" + user_id))
        for n in names:
            if n:
                self._seen_mods.add((platform, normalize(n)))

    def is_exempt(self, platform: str, user_id: str = "", username: str = "", display_name: str = "") -> bool:
        """A moderator or the streamer, as far as Core can tell without the live chat badges."""
        if user_id and (platform, "id:" + user_id) in self._seen_mods:
            return True
        if any(n and (platform, normalize(n)) in self._seen_mods for n in (username, display_name)):
            return True
        if self.staff is not None:
            try:
                return bool(self.staff(platform, user_id, username))
            except Exception:
                log.exception("red flags: staff check failed")
        return False

    # ------------------------------------------------------------------
    # Check past chat
    # ------------------------------------------------------------------

    def scan_past_sync(self, rows: Iterable[dict], max_people: int = MAX_PAST_PEOPLE) -> dict:
        """Run the current phrases over saved chat lines (oldest first). Chatters already on
        the list are left out, and so are mods and the streamer when ``skip_mods`` is on.
        Returns ``{"scanned", "people": [...], "more"}``; each person carries the first line
        that matched (``phrase``/``message``/``timestamp``), ``count`` and a few ``examples``."""
        scanned = 0
        people: dict[tuple[str, str], dict] = {}
        more = False
        if not self._patterns:
            return {"scanned": 0, "people": [], "more": False}
        # one pass with every phrase joined; the phrase itself is only looked up on a hit
        anything = self._any
        exempt: dict[tuple[str, str, str], bool] = {}
        for row in rows:
            scanned += 1
            text = str(row.get("message") or "")
            if not text or not anything.search(normalize(text)):
                continue
            plat = str(row.get("platform") or "")
            uid = str(row.get("platform_user_id") or "")
            username = str(row.get("username") or "")
            display = str(row.get("display_name") or "")
            if self.is_flagged(plat, uid, username, display):
                continue
            if self.skip_mods:
                ek = (plat, uid, username)
                if ek not in exempt:
                    exempt[ek] = self.is_exempt(plat, uid, username, display)
                if exempt[ek]:
                    continue
            key = (plat, uid or "name:" + normalize(username or display))
            person = people.get(key)
            if person is None:
                if len(people) >= max_people:
                    more = True
                    continue
                phrase = self.match(text) or ""
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

    async def flag(self, platform: str, user_id: str, username: str, display_name: str = "",
                   phrase: str = "", message: str = "", source: str = "manual") -> dict:
        row = await self.store.add_red_flag(
            platform=str(platform or ""), platform_user_id=str(user_id or ""),
            username=normalize(username).strip(), display_name=str(display_name or username or "").strip(),
            phrase=phrase, message=message, source=source,
        )
        await self.store._run(self.reload)
        return row

    async def unflag(self, flag_id: int) -> Optional[dict]:
        row = await self.store.remove_red_flag(int(flag_id))
        await self.store._run(self.reload)
        return row

    async def list(self) -> list[dict]:
        return await self.store._run(self.store.list_red_flagged_sync)

    async def scan_past(self) -> dict:
        """``scan_past_sync`` over the whole saved chat log, off the event loop."""
        def _scan():
            return self.scan_past_sync(self.store.iter_chat_sync())
        return await self.store._run(_scan)

    def info(self) -> dict:
        return {"enabled": self.enabled, "skip_mods": self.skip_mods, "phrases": list(self.phrases)}


def matching_recent(items: Iterable[dict], platform: str, user_id: str, *names: str) -> list[dict]:
    """Chat payloads (``recent_chat`` entries) sent by this chatter."""
    want = {normalize(n) for n in names if n}
    out = []
    for item in items:
        user = item.get("user") or {}
        if platform and item.get("platform") != platform:
            continue
        if user_id and str(user.get("id") or "") == str(user_id):
            out.append(item)
        elif want & {normalize(user.get("username") or ""), normalize(user.get("display_name") or "")}:
            out.append(item)
    return out
