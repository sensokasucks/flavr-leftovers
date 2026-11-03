"""
Text-to-speech text clean-up: what a line turns into before Core sends it to the TTS server.

core/tts.py (TtsEngine) runs every line through ``TextFilter`` before it is queued: chat
lines, ``!tts`` messages, paid messages, alert headlines, highlights and plugin lines alike.
The dashboard's "Blocked words test" box (POST /api/admin/tts/filter-test) shows the same
result, so what the streamer sees there is exactly what would be read aloud.

Steps, in order (``TextFilter.clean``):
  1. emotes are taken out (``strip_emotes``: Twitch / 7TV ranges and Kick ``[emote:ID:NAME]``
     tokens), so the voice never reads "KEKW KEKW KEKW"
  2. links are taken out (``tts.filters.drop_links``, on by default)
  3. blocked words and phrases (``tts.filters.blocked``, plus the red-flag phrases when
     ``use_red_flags`` is on): skip the whole line, or say "beep" / nothing in their place
     (``tts.filters.on_match``: skip | beep | remove)
  4. long runs are squeezed ("noooooooo" -> "nooo", "!!!!!" -> "!")
  5. the line is cut to ``tts.max_chars`` characters at a word boundary

Blocked-word matching (``BlockList``) is whole-word and ignores case, accents and the usual
dodges: "1d10t", "i.d.i.o.t", "i d i o t" and "iiidiot" all match "idiot". ``word*`` matches
words starting with "word". A phrase ("go back to") matches those words in a row.
Chatter names are checked too (``TextFilter.clean_name``): a blocked name is read as "someone".
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, List, Optional, Sequence, Tuple

# Kick writes emotes into the message text as [emote:123:NAME] (same pattern as overlay/chat.js)
KICK_EMOTE_RE = re.compile(r"\[emote:\d+:[^\]]*\]")
# http(s) links, www. links, and bare domains with a common ending ("example.com/abc")
LINK_RE = re.compile(
    r"(?:https?://\S+|www\.\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|tv|gg|io|co|me|ly|be|xyz|info|live|app|link|shop|ru|uk|de)\b\S*)",
    re.IGNORECASE,
)
# What a blocked word becomes with on_match "beep"
BEEP = "beep"
# What a blocked chatter name is read as
SOMEONE = "someone"
# Words in a message are split on spaces and on these joiners ("you-idiot" -> you, idiot).
# Dots stay inside a word so "i.d.i.o.t" is one word ("idiot") after clean-up.
_WORD_RE = re.compile(r"[^\s\-_/\\,;:]+")
# Numbers and symbols people use as letters to dodge a filter
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
                       "@": "a", "$": "s", "!": "i", "|": "i", "+": "t"})
# Letters repeated 4 or more times (squeezed to 3) and punctuation repeated (squeezed to 1)
_LONG_LETTERS = re.compile(r"(\w)\1{3,}")
_LONG_PUNCT = re.compile(r"([!?.,~*])\1+")
ON_MATCH = ("skip", "beep", "remove")


def _fold(text: str) -> str:
    """Lower case with accents taken off ("Ídiót" -> "idiot")."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def norm_word(word: str) -> str:
    """One word as the blocked-word check sees it: lower case, no accents, numbers and symbols
    read as letters, only a-z kept, and every run of one letter squeezed to one
    ("1d10t" -> "idiot", "iiidiot" -> "idiot", "Book" -> "bok"). Both the blocked entries and
    the message words go through this, so the squeezing never stops a match."""
    text = _fold(word).translate(_LEET)
    text = re.sub(r"[^a-z]", "", text)
    return re.sub(r"(.)\1+", r"\1", text)


def strip_emotes(message: str, emotes: Optional[Sequence[Any]] = None) -> Tuple[str, bool]:
    """``message`` without its emotes, and whether any were taken out.

    ``emotes`` are chat payload ranges ({"start", "end"} character positions, end included,
    as Twitch / 7TV send them and overlay/chat.js draws them); Kick's [emote:ID:NAME] tokens
    in the text are taken out too."""
    text = str(message or "")
    removed = False
    spans = []
    for e in emotes or []:
        try:
            start, end = int(e.get("start")), int(e.get("end"))
        except (AttributeError, TypeError, ValueError):
            continue
        if 0 <= start <= end < len(text):
            spans.append((start, end))
    if spans:
        keep = []
        pos = 0
        for start, end in sorted(spans):
            if start < pos:
                continue
            keep.append(text[pos:start])
            pos = end + 1
        keep.append(text[pos:])
        text = " ".join(keep)
        removed = True
    text, n = KICK_EMOTE_RE.subn(" ", text)
    removed = removed or n > 0
    return " ".join(text.split()), removed


def parse_blocked(raw: Any) -> List[str]:
    """The blocked list as clean lines: from a list, or text with one entry per line. Empty
    lines and "# notes" are dropped, duplicates (ignoring case) kept once, each line <= 100 chars."""
    if isinstance(raw, str):
        items: Iterable[Any] = raw.splitlines()
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = []
    out: List[str] = []
    seen = set()
    for item in items:
        line = " ".join(str(item or "").split())[:100]
        if not line or line.startswith("#"):
            continue
        if line.lower() in seen:
            continue
        seen.add(line.lower())
        out.append(line)
    return out[:2000]


class BlockList:
    """Blocked words and phrases, ready to match. Built from ``tts.filters.blocked`` (and the
    red-flag phrases when ``use_red_flags`` is on) by TextFilter; rebuilt on every settings change."""

    def __init__(self, entries: Iterable[str]):
        # each entry: a list of (word, is_prefix) in order; "idiot*" = any word starting "idiot"
        self.entries: List[List[Tuple[str, bool]]] = []
        for entry in entries:
            words = []
            for raw in str(entry).split():
                prefix = raw.endswith("*")
                word = norm_word(raw.rstrip("*"))
                if word:
                    words.append((word, prefix))
            if words:
                self.entries.append(words)

    def __bool__(self) -> bool:
        return bool(self.entries)

    @staticmethod
    def _tokens(text: str) -> Tuple[List[Tuple[int, int, str]], List[Tuple[int, int, str]]]:
        """The words of ``text`` as (start, end, normalised word), in reading order, plus extra
        words: each run of 3 or more single letters ("i d i o t") joined into one word."""
        words = [(m.start(), m.end(), norm_word(m.group())) for m in _WORD_RE.finditer(text)]
        words = [w for w in words if w[2]]
        joined = []
        i = 0
        while i < len(words):
            j = i
            while j < len(words) and len(words[j][2]) == 1:
                j += 1
            if j - i >= 3:
                joined.append((words[i][0], words[j - 1][1], norm_word("".join(w[2] for w in words[i:j]))))
            i = max(j, i + 1)
        return words, joined

    @staticmethod
    def _same(word: str, pattern: Tuple[str, bool]) -> bool:
        want, prefix = pattern
        return word.startswith(want) if prefix else word == want

    def find(self, text: str) -> List[Tuple[int, int]]:
        """Character spans of ``text`` that are blocked (whole words / phrases), sorted."""
        if not self.entries or not text:
            return []
        words, joined = self._tokens(text)
        spans = []
        for entry in self.entries:
            n = len(entry)
            if n == 1:
                spans.extend((s, e) for s, e, w in words + joined if self._same(w, entry[0]))
                continue
            # a phrase: its words in a row
            for i in range(len(words) - n + 1):
                if all(self._same(words[i + k][2], entry[k]) for k in range(n)):
                    spans.append((words[i][0], words[i + n - 1][1]))
        return sorted(set(spans))

    def in_name(self, name: str) -> bool:
        """True when a chatter name holds a blocked word anywhere ("xX_idiot_Xx"). Names are
        often words run together, so a name is checked by substring; entries of 1-2 letters
        are skipped there (they would hit too many innocent names)."""
        flat = norm_word(name)
        if not flat:
            return False
        for entry in self.entries:
            joined = "".join(w for w, _ in entry)
            if len(joined) >= 3 and joined in flat:
                return True
        return False


def _cut(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` characters, at the last space when there is one."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = head.rfind(" ")
    if space > limit // 2:
        head = head[:space]
    return head.rstrip(" ,;:-")


class TextFilter:
    """The clean-up every TTS line goes through (see the module notes for the steps).

    Made by TtsEngine from the ``tts`` settings (core/tts.py read_settings). ``extra`` is a
    list of more blocked entries (the red-flag phrases when ``filters.use_red_flags`` is on)."""

    def __init__(self, settings: dict, extra: Iterable[str] = ()):
        filters = settings.get("filters") or {}
        self.blocked = BlockList(list(parse_blocked(filters.get("blocked"))) + list(extra))
        mode = str(filters.get("on_match") or "skip").lower()
        self.on_match = mode if mode in ON_MATCH else "skip"
        self.drop_links = bool(filters.get("drop_links", True))
        self.check_names = bool(filters.get("check_names", True))
        try:
            self.max_chars = max(20, min(1000, int(settings.get("max_chars") or 300)))
        except (TypeError, ValueError):
            self.max_chars = 300

    def clean_name(self, name: str) -> str:
        """A chatter name to read aloud: "someone" when it holds a blocked word, else as is
        (underscores read as spaces)."""
        text = " ".join(str(name or "").replace("_", " ").split())
        if not text:
            return SOMEONE
        if self.check_names and self.blocked.in_name(text):
            return SOMEONE
        return text

    def clean(self, text: str) -> Tuple[str, str]:
        """(text to read, "") when the line can be read, or ("", why) when it is skipped.
        ``why`` is short and plain: "blocked word", "nothing left to read". Emotes must already
        be out (``strip_emotes``), since their positions point into the original message."""
        out = " ".join(str(text or "").split())
        if self.drop_links:
            out = " ".join(LINK_RE.sub(" ", out).split())
        spans = self.blocked.find(out)
        if spans:
            if self.on_match == "skip":
                return "", "blocked word"
            word = BEEP if self.on_match == "beep" else ""
            parts = []
            pos = 0
            for start, end in spans:
                if start < pos:
                    continue
                parts.append(out[pos:start])
                parts.append(word)
                pos = end
            parts.append(out[pos:])
            out = " ".join("".join(parts).split())
        out = _LONG_LETTERS.sub(lambda m: m.group(1) * 3, out)
        out = _LONG_PUNCT.sub(r"\1", out)
        out = _cut(out, self.max_chars)
        if not re.search(r"\w", out):
            return "", "nothing left to read"
        return out, ""
