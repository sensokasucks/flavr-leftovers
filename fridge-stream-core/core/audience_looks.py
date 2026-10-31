"""
Audience looks for Stream Rooms: how its chat audience's speech bubbles and silhouettes look,
edited on the dashboard's Audience looks page (admin/audience-looks.js) and sent to Stream Rooms
over ``/ws`` as ``{"type": "audience_looks", "data": ...}`` (on connect and after every save).
Stream Rooms draws everything; Core only keeps the settings.

Kept in ``data/audience_looks.json``:

    bubble_theme  "light" | "dark" | "custom" (custom = the "bubble" style below)
    bubble        the custom bubble style: {key: value}
    silhouette    the silhouette style everyone gets: {key: value}
    saved         the streamer's own presets: {"bubble": {name: style}, "silhouette": {name: style}}
    groups        looks per group: {group: {"bubble": name, "silhouette": name | "a|b|c" (random mix)}}

The style keys and their meaning are Stream Rooms' (core/audience/audience_style.gd there:
BUBBLE_DEFAULTS, FIGURE_DEFAULTS, GROUPS); keep the lists below in sync with it. Stream Rooms
checks and clamps every value again, so this only keeps the file tidy and small.
The payload also says whether the looks were ever saved ("edited").
A silhouette picture is a stored file (core/media_library.py), written ``"media:<name>"`` in a
style's "file"; the payload adds each picture's url and version so Stream Rooms can fetch it.
The class is also a stored-files user (media_refs / media_renamed / media_forgotten /
write_settings), like the overlay styles, so Rename and Delete on the Stored files page follow.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("core.audience_looks")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "audience_looks.json"

# Style keys Stream Rooms knows (AudienceStyle.BUBBLE_DEFAULTS / FIGURE_DEFAULTS); others are dropped.
BUBBLE_KEYS = ("shape", "fill", "fill_mix", "text", "name_mode", "name_color", "outline", "outline_mode",
               "outline_color", "text_size", "bold", "roundness", "tail", "width", "paid", "highlighted")
FIGURE_KEYS = ("shape", "file", "paint", "color", "brightness", "size", "head_x", "head_y", "head_r", "crowd")
# Groups in the order they win (AudienceStyle.GROUPS), and the separator of a random mix.
GROUPS = ("mod", "vip", "sub", "kick", "twitch", "youtube", "other", "all")
MIX_SEP = "|"
THEMES = ("light", "dark", "custom")
MEDIA_PREFIX = "media:"
# Most saved presets of each kind, longest preset name, biggest file (bytes).
MAX_PRESETS = 200
MAX_NAME = 40
MAX_FILE_BYTES = 512 * 1024


def _clean_style(raw: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    """Only known keys with plain values (text up to 200 characters); {} for anything else."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k in keys:
        v = raw.get(k)
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:200]
    return out


def _clean_name(raw: Any) -> str:
    """A preset name: trimmed, no mix separator, at most MAX_NAME characters."""
    return str(raw or "").replace(MIX_SEP, " ").strip()[:MAX_NAME]


def normalize(raw: Any) -> dict[str, Any]:
    """A complete, tidy looks dict from whatever was saved or sent (missing parts empty)."""
    raw = raw if isinstance(raw, dict) else {}
    theme = str(raw.get("bubble_theme") or "light")
    saved_in = raw.get("saved") if isinstance(raw.get("saved"), dict) else {}
    saved: dict[str, dict[str, Any]] = {}
    for kind, keys in (("bubble", BUBBLE_KEYS), ("silhouette", FIGURE_KEYS)):
        mine = saved_in.get(kind) if isinstance(saved_in.get(kind), dict) else {}
        saved[kind] = {}
        for name, style in list(mine.items())[:MAX_PRESETS]:
            n = _clean_name(name)
            if n and isinstance(style, dict):
                saved[kind][n] = _clean_style(style, keys)
    groups: dict[str, dict[str, str]] = {}
    groups_in = raw.get("groups") if isinstance(raw.get("groups"), dict) else {}
    for g in GROUPS:
        looks = groups_in.get(g)
        if not isinstance(looks, dict):
            continue
        kept = {k: str(looks[k])[:2000] for k in ("bubble", "silhouette") if str(looks.get(k) or "").strip()}
        if kept:
            groups[g] = kept
    return {
        "bubble_theme": theme if theme in THEMES else "light",
        "bubble": _clean_style(raw.get("bubble"), BUBBLE_KEYS),
        "silhouette": _clean_style(raw.get("silhouette"), FIGURE_KEYS),
        "saved": saved,
        "groups": groups,
    }


class AudienceLooks:
    """data/audience_looks.json, with the payload Stream Rooms gets.

    ``on_change`` (set by main.py) is called with the payload after every save, to send it to
    every /ws client. ``media`` returns the stored-files library (for the pictures' urls).
    """

    def __init__(self, path: Optional[Path] = None, media: Optional[Callable[[], Any]] = None):
        self.path = Path(path) if path else DATA_FILE
        self._media = media
        self._lock = threading.RLock()
        self.on_change: Optional[Callable[[dict[str, Any]], None]] = None

    # ── file ────────────────────────────────────────────────
    def load(self) -> dict[str, Any]:
        """The saved looks (defaults when the file is missing or broken)."""
        with self._lock:
            try:
                return normalize(json.loads(self.path.read_text(encoding="utf-8") or "{}"))
            except (OSError, ValueError):
                return normalize({})

    def save(self, looks: Any) -> dict[str, Any]:
        """Tidy and save; returns the payload (and hands it to on_change). ValueError when too big."""
        clean = normalize(looks)
        text = json.dumps(clean, indent=1, sort_keys=True)
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Too many saved looks: delete some first.")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(text + "\n", encoding="utf-8")
            tmp.replace(self.path)
        payload = self.payload(clean)
        if self.on_change is not None:
            try:
                self.on_change(payload)
            except Exception:
                log.exception("Sending audience looks failed")
        return payload

    # ── what Stream Rooms gets ──────────────────────────────
    def payload(self, looks: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """The looks plus ``pictures``: {stored file name: {url, version}} for every picture used,
        and ``edited``: whether the looks were ever saved (Stream Rooms ignores the packet until
        then, so a fresh Core doesn't reset looks Stream Rooms already had)."""
        looks = looks if looks is not None else self.load()
        pictures: dict[str, dict[str, Any]] = {}
        lib = self._media() if self._media else None
        for name in self._picture_names(looks):
            entry = lib.get(name) if lib is not None else None
            if entry and entry.get("kind") == "image":
                pictures[name] = {"url": entry["url"], "version": entry["version"]}
        return {**looks, "pictures": pictures, "edited": self.path.exists()}

    @staticmethod
    def _figures(looks: dict[str, Any]) -> list[dict[str, Any]]:
        """Every silhouette style in the looks (the main one and the saved ones)."""
        return [looks.get("silhouette") or {}] + list(((looks.get("saved") or {}).get("silhouette") or {}).values())

    def _picture_names(self, looks: dict[str, Any]) -> list[str]:
        """Stored file names the silhouette styles use ("media:<name>" in "file")."""
        names: list[str] = []
        for f in self._figures(looks):
            file = str(f.get("file") or "")
            if file.startswith(MEDIA_PREFIX) and file[len(MEDIA_PREFIX):] not in names:
                names.append(file[len(MEDIA_PREFIX):])
        return names

    # ── stored-files user (api/admin_routes.py _media_users) ─
    def media_refs(self) -> list[dict[str, str]]:
        """Each silhouette style that uses a stored picture: {name, overlay, slot, kind}."""
        looks = self.load()
        out = []
        own = (looks.get("saved") or {}).get("silhouette") or {}
        for slot, f in [("Main silhouette", looks.get("silhouette") or {})] + list(own.items()):
            file = str(f.get("file") or "")
            if file.startswith(MEDIA_PREFIX):
                out.append({"name": file[len(MEDIA_PREFIX):], "overlay": "audience looks", "slot": slot, "kind": "image"})
        return out

    def _rewrite(self, old: str, new: Optional[str]) -> int:
        """Point silhouettes at ``new`` instead of ``old`` (None = back to the classic shape); saves."""
        looks = self.load()
        n = 0
        for f in self._figures(looks):
            if str(f.get("file") or "") == MEDIA_PREFIX + old:
                if new is None:
                    f["shape"] = "classic"
                    f.pop("file", None)
                else:
                    f["file"] = MEDIA_PREFIX + new
                n += 1
        if n:
            self.save(looks)
        return n

    def media_renamed(self, old: str, new: str) -> int:
        """A stored file was renamed: follow it. Returns how many styles changed."""
        return self._rewrite(old, new)

    def media_forgotten(self, name: str) -> int:
        """A stored file was deleted: those silhouettes go back to the classic shape. Returns how many."""
        return self._rewrite(name, None)

    def write_settings(self, **_kw) -> None:
        """A picture was replaced: send the looks again so Stream Rooms fetches the new version."""
        self.save(self.load())


_default: Optional[AudienceLooks] = None


def default_looks() -> AudienceLooks:
    """The one store for data/audience_looks.json (main.py sets on_change on it)."""
    global _default
    if _default is None:
        from core.media_library import default_library

        _default = AudienceLooks(media=default_library)
    return _default
