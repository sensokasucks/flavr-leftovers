"""
The look of an overlay page, kept next to the page itself (alerts, chat).

Each styled overlay has three things in ``overlay/``:
  - ``<name>-custom.css``: the streamer's own CSS, pasted in the dashboard (or copied from a
    Streamlabs / StreamElements / OBS "Custom CSS" box; the pages use those tools' ids and
    classes so packs drop in).
  - ``<name>-settings.json``: skin, a css_version stamp the page polls so a save applies live,
    and small options (hide messages after N s, sound volume, ...).
  - ``<name>-css/<slot>.css``: extra saved stylesheets ("money", "twitch"); a page picks one
    with ``?css=<slot>`` so each OBS source can have its own look.
  - pictures, videos and sounds per slot: a pick of a file in the shared library
    (``core/media_library.py``, ``data/media/``, served at ``/media/``), kept as ``picks`` in the
    settings. A slot with no pick still uses a file dropped by hand into ``assets/<name>/``
    (``follow.gif``, ``raid.webm``, ``message.mp3``); Core copies those into the library at start.
    The page gets the list of what exists so it never probes for missing files.

``core/alerts.py`` wraps one of these for the alerts overlay; the chat overlay has its own.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from core.css_templates import fill_placeholders

log = logging.getLogger("core.overlay_style")

OVERLAY_DIR = Path(__file__).resolve().parent.parent / "overlay"
MAX_CUSTOM_CSS_BYTES = 256_000
MAX_ASSET_BYTES = 15 * 1024 * 1024
MAX_CSS_SLOTS = 30
_CSS_BLOCK = re.compile(r"<\s*/?\s*script|<\s*/?\s*style|javascript:|expression\s*\(", re.IGNORECASE)
_SLOT_RE = re.compile(r"[^a-z0-9_-]+")

# preference order when several formats of one slot exist (video first, as the alerts always did)
IMAGE_EXTS = ("webm", "mp4", "gif", "webp", "png", "jpg", "jpeg", "svg")
SOUND_EXTS = ("mp3", "ogg", "wav", "m4a")


def sniff(data: bytes) -> Optional[str]:
    """File type from the first bytes (never from the name). Returns an extension or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] in (0xFB, 0xF3, 0xF2, 0xFA)):
        return "mp3"
    if data[4:8] == b"ftyp":
        # one container for both: the brand says whether it's audio only (M4A) or a video (MP4)
        return "m4a" if data[8:11] in (b"M4A", b"M4B", b"M4P") else "mp4"
    if data[:4] == b"wOF2":
        return "woff2"
    if data[:4] == b"wOFF":
        return "woff"
    if data[:4] in (b"\x00\x01\x00\x00", b"true"):
        return "ttf"
    if data[:4] == b"OTTO":
        return "otf"
    return None


def clean_slot(raw: str) -> str:
    return _SLOT_RE.sub("-", str(raw or "").strip().lower()).strip("-_")[:40]


class OverlayStyle:
    def __init__(self, name: str, skins: tuple[str, ...], image_slots: tuple[str, ...] = (),
                 sound_slots: tuple[str, ...] = (), options: Optional[dict[str, Any]] = None,
                 ranges: Optional[dict[str, tuple[float, float]]] = None, overlay_dir: Optional[Path] = None,
                 allow_video: bool = False, library: Any = None):
        self.name = name
        self.skins = skins
        self.image_slots = image_slots
        self.sound_slots = sound_slots
        self.default_options = dict(options or {})
        self.ranges = dict(ranges or {})
        self.overlay_dir = overlay_dir or OVERLAY_DIR
        self.allow_video = allow_video      # picture slots may hold a WebM / MP4 (alerts) or not (chat)
        self._library = library             # core.media_library.MediaLibrary; None = data/media

    # ── paths ───────────────────────────────────────────────
    def _root(self, overlay_dir: Optional[Path]) -> Path:
        return overlay_dir or self.overlay_dir

    def css_path(self, overlay_dir: Optional[Path] = None) -> Path:
        return self._root(overlay_dir) / f"{self.name}-custom.css"

    def settings_path(self, overlay_dir: Optional[Path] = None) -> Path:
        return self._root(overlay_dir) / f"{self.name}-settings.json"

    def css_slots_dir(self, overlay_dir: Optional[Path] = None) -> Path:
        return self._root(overlay_dir) / f"{self.name}-css"

    def assets_dir(self, overlay_dir: Optional[Path] = None) -> Path:
        return self._root(overlay_dir) / "assets" / self.name

    # ── settings ────────────────────────────────────────────
    def read_settings(self, overlay_dir: Optional[Path] = None) -> dict[str, Any]:
        skin = self.skins[0]
        css_version = 0
        options = dict(self.default_options)
        path = self.settings_path(overlay_dir)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
                if isinstance(data, dict):
                    if data.get("skin") in self.skins:
                        skin = data["skin"]
                    css_version = int(data.get("css_version") or 0)
                    options.update(self.clean_options(data.get("options")))
            except (OSError, TypeError, ValueError):
                pass
        media, sounds = self.list_assets(overlay_dir)
        return {"skin": skin, "css_version": css_version, "options": options, "media": media, "sounds": sounds,
                "css_slots": self.list_css_slots(overlay_dir)}

    def clean_options(self, raw: Any) -> dict[str, Any]:
        """Keep only known options, coerced to the default's type and clamped to its range."""
        out: dict[str, Any] = {}
        if not isinstance(raw, dict):
            return out
        for key, default in self.default_options.items():
            if key not in raw:
                continue
            val = raw[key]
            try:
                if isinstance(default, bool):
                    val = bool(val) if not isinstance(val, str) else val.strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int):
                    val = int(float(val))
                elif isinstance(default, float):
                    val = float(val)
                else:
                    val = str(val)[:200]
            except (TypeError, ValueError):
                continue
            lo_hi = self.ranges.get(key)
            if lo_hi and not isinstance(default, (bool, str)):
                val = max(lo_hi[0], min(lo_hi[1], val))
                val = int(val) if isinstance(default, int) else float(val)
            out[key] = val
        return out

    def write_settings(self, skin: Optional[str] = None, bump_css: bool = False,
                       options: Optional[dict[str, Any]] = None, overlay_dir: Optional[Path] = None) -> dict[str, Any]:
        current = self.read_settings(overlay_dir)
        if skin in self.skins:
            current["skin"] = skin
        if bump_css:
            current["css_version"] = int(time.time())
        if options:
            current["options"].update(self.clean_options(options))
        payload = {"skin": current["skin"], "css_version": current["css_version"], "options": current["options"]}
        picks = self.read_picks(overlay_dir)
        if picks["image"] or picks["sound"]:
            payload["picks"] = picks
        path = self.settings_path(overlay_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.read_settings(overlay_dir)

    # ── custom CSS ──────────────────────────────────────────
    @staticmethod
    def _slot_name(slot: Optional[str]) -> str:
        """"" for the default stylesheet, else a clean slot name."""
        name = clean_slot(slot or "")
        return "" if name in ("", "default") else name

    def _css_file(self, slot: Optional[str], overlay_dir: Optional[Path]) -> Path:
        name = self._slot_name(slot)
        if not name:
            return self.css_path(overlay_dir)
        return self.css_slots_dir(overlay_dir) / f"{name}.css"

    def read_css(self, overlay_dir: Optional[Path] = None, slot: Optional[str] = None) -> str:
        path = self._css_file(slot, overlay_dir)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def write_css(self, css: str, overlay_dir: Optional[Path] = None, slot: Optional[str] = None) -> dict[str, Any]:
        if not isinstance(css, str):
            raise ValueError("css must be a string")
        raw = css.replace("\r\n", "\n")
        if len(raw.encode("utf-8")) > MAX_CUSTOM_CSS_BYTES:
            raise ValueError("Custom CSS is too large (max 256 KB)")
        if _CSS_BLOCK.search(raw):
            raise ValueError("Custom CSS cannot contain script/style tags or expressions")
        if slot and not self._slot_name(slot) and clean_slot(slot) != "default":
            raise ValueError("Give the stylesheet a name made of letters, numbers, - or _.")
        name = self._slot_name(slot)
        if name and name not in self.list_css_slots(overlay_dir) and len(self.list_css_slots(overlay_dir)) >= MAX_CSS_SLOTS:
            raise ValueError(f"That's the most saved stylesheets ({MAX_CSS_SLOTS}). Delete one first.")
        # a Streamlabs / StreamElements template's {font_size} / {{fontSize}} get real values
        raw, filled = fill_placeholders(raw)
        path = self._css_file(slot, overlay_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        # a slot's version is its file time; the default sheet bumps css_version as before
        out = self.write_settings(bump_css=not name, overlay_dir=overlay_dir)
        out["placeholders_filled"] = filled
        return out

    def list_css_slots(self, overlay_dir: Optional[Path] = None) -> dict[str, int]:
        """{slot: version} for the saved extra stylesheets (the version changes on every save)."""
        folder = self.css_slots_dir(overlay_dir)
        out: dict[str, int] = {}
        if not folder.is_dir():
            return out
        for path in sorted(folder.glob("*.css")):
            name = self._slot_name(path.stem)
            if name and name == path.stem:
                try:
                    out[name] = int(path.stat().st_mtime * 1000)
                except OSError:
                    continue
        return out

    def delete_css_slot(self, slot: str, overlay_dir: Optional[Path] = None) -> bool:
        name = self._slot_name(slot)
        if not name:
            return False
        path = self.css_slots_dir(overlay_dir) / f"{name}.css"
        if not path.is_file():
            return False
        path.unlink()
        return True

    # ── assets (pictures, videos, sounds) ───────────────────
    # A slot points at a file in the shared library (core/media_library.py) by name ("picks" in
    # <name>-settings.json). A slot with no pick still shows a file dropped by hand into
    # assets/<name>/ (``follow.gif``); Core copies those into the library at start (import_legacy).
    @property
    def library(self):
        if self._library is None:
            from core.media_library import default_library

            return default_library()
        return self._library

    def read_picks(self, overlay_dir: Optional[Path] = None) -> dict[str, dict[str, str]]:
        """{"image": {slot: file name}, "sound": {slot: file name}}"""
        out: dict[str, dict[str, str]] = {"image": {}, "sound": {}}
        path = self.settings_path(overlay_dir)
        if not path.is_file():
            return out
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return out
        picks = data.get("picks") if isinstance(data, dict) else None
        if not isinstance(picks, dict):
            return out
        for kind, slots in (("image", self.image_slots), ("sound", self.sound_slots)):
            raw = picks.get(kind)
            if isinstance(raw, dict):
                out[kind] = {k: str(v) for k, v in raw.items() if k in slots and isinstance(v, str) and v}
        return out

    def _write_picks(self, picks: dict[str, dict[str, str]], overlay_dir: Optional[Path]) -> None:
        path = self.settings_path(overlay_dir)
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8") or "{}")
                data = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                data = {}
        if picks.get("image") or picks.get("sound"):
            data["picks"] = {"image": dict(sorted(picks.get("image", {}).items())),
                             "sound": dict(sorted(picks.get("sound", {}).items()))}
        else:
            data.pop("picks", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def _picture_kinds(self) -> tuple[str, ...]:
        return ("image", "video") if self.allow_video else ("image",)

    def list_assets(self, overlay_dir: Optional[Path] = None) -> tuple[dict[str, str], dict[str, str]]:
        """({image slot: url}, {sound slot: url}). A library pick gives ``/media/<file>?v=…``; a file
        dropped in by hand gives a url relative to the overlay page (``assets/<name>/<file>``)."""
        media: dict[str, str] = {}
        sounds: dict[str, str] = {}
        picks = self.read_picks(overlay_dir)
        lib = self.library
        for kind, out in (("image", media), ("sound", sounds)):
            for slot, name in picks[kind].items():
                entry = lib.get(name)
                if entry and (entry["kind"] == "sound") == (kind == "sound"):
                    out[slot] = entry["url"]
        folder = self.assets_dir(overlay_dir)
        if not folder.is_dir():
            return media, sounds
        for slot in self.image_slots:
            if slot in media:
                continue
            for ext in IMAGE_EXTS:
                if (folder / f"{slot}.{ext}").is_file():
                    media[slot] = f"assets/{self.name}/{slot}.{ext}"
                    break
        for slot in self.sound_slots:
            if slot in sounds:
                continue
            for ext in SOUND_EXTS:
                if (folder / f"{slot}.{ext}").is_file():
                    sounds[slot] = f"assets/{self.name}/{slot}.{ext}"
                    break
        return media, sounds

    def slot_kind(self, slot: str, ext: Optional[str] = None) -> Optional[str]:
        """"image" or "sound" for a slot. A slot that takes both (the alerts' kinds) is decided
        by the file type when one is given."""
        image_ok = slot in self.image_slots
        sound_ok = slot in self.sound_slots
        if image_ok and sound_ok and ext is not None:
            return "sound" if ext in SOUND_EXTS else "image"
        if image_ok:
            return "image"
        if sound_ok:
            return "sound"
        return None

    def _check_for_slot(self, slot: str, ext: Optional[str]) -> str:
        """The slot's kind for a file of this type, or ValueError."""
        if self.slot_kind(slot) is None:
            raise ValueError(f"Unknown slot '{slot}'.")
        kind = self.slot_kind(slot, ext)
        pictures = ("png", "jpeg", "jpg", "gif", "webp") + (("webm", "mp4") if self.allow_video else ())
        if kind == "image" and ext not in pictures:
            raise ValueError("Pictures must be PNG, JPEG, GIF, WebP or a WebM / MP4 video." if self.allow_video
                             else "Pictures must be PNG, JPEG, GIF or WebP.")
        if kind == "sound" and ext not in ("mp3", "ogg", "wav", "m4a"):
            raise ValueError("Sounds must be MP3, OGG, WAV or M4A.")
        return kind  # type: ignore[return-value]

    def _default_name(self, slot: str, kind: str) -> str:
        """Stored-file name for an upload with no file name: alerts-follow, alerts-follow-sound."""
        both = slot in self.image_slots and slot in self.sound_slots
        return f"{self.name}-{slot}" + ("-sound" if both and kind == "sound" else "")

    def pick(self, slot: str, file_name: str, kind: Optional[str] = None,
             overlay_dir: Optional[Path] = None) -> str:
        """Point a slot at a library file. Returns the url."""
        slot = clean_slot(slot)
        entry = self.library.get(file_name)
        if entry is None:
            raise ValueError(f"No stored file called '{file_name}'.")
        if entry["kind"] == "font":
            raise ValueError("Fonts can only be used from custom CSS.")
        if kind == "sound" and entry["kind"] != "sound":
            raise ValueError("That's a picture; pick a sound.")
        if kind == "image" and entry["kind"] == "sound":
            raise ValueError("That's a sound; pick a picture.")
        slot_kind = self._check_for_slot(slot, entry["ext"])
        if kind in ("image", "sound") and slot_kind != kind:
            raise ValueError(f"'{slot}' has no {kind} slot.")
        picks = self.read_picks(overlay_dir)
        picks[slot_kind][slot] = entry["name"]
        self._write_picks(picks, overlay_dir)
        return entry["url"]

    def save_asset(self, slot: str, data: bytes, overlay_dir: Optional[Path] = None, filename: str = "") -> str:
        """Store an upload in the library and point the slot at it. Returns the url."""
        from core.media_library import MAX_BYTES, MAX_VIDEO_BYTES, name_from_filename

        slot = clean_slot(slot)
        if self.slot_kind(slot) is None:
            raise ValueError(f"Unknown slot '{slot}'.")
        if not data:
            raise ValueError("The file is empty.")
        ext = sniff(data)
        limit = MAX_VIDEO_BYTES if ext in ("webm", "mp4") else MAX_BYTES
        if len(data) > limit:
            raise ValueError(f"Too big ({len(data) // 1024} KB). The limit is {limit // (1024 * 1024)} MB.")
        kind = self._check_for_slot(slot, ext)
        entry, _reused = self.library.save(data, name_from_filename(filename) or self._default_name(slot, kind))
        return self.pick(slot, entry["name"], kind, overlay_dir)

    def save_asset_base64(self, slot: str, b64: str, overlay_dir: Optional[Path] = None, filename: str = "") -> str:
        from core.media_library import decode_base64

        return self.save_asset(slot, decode_base64(b64), overlay_dir, filename)

    def delete_asset(self, slot: str, kind: Optional[str] = None, overlay_dir: Optional[Path] = None) -> bool:
        """Empty a slot: forget its pick and remove a file dropped in by hand (the library file stays).
        ``kind`` ("image" / "sound") matters for slots that take both."""
        slot = clean_slot(slot)
        if kind not in ("image", "sound"):
            kind = self.slot_kind(slot)
        if kind is None or self.slot_kind(slot) is None:
            return False
        if kind == "sound" and slot not in self.sound_slots:
            return False
        if kind == "image" and slot not in self.image_slots:
            return False
        picks = self.read_picks(overlay_dir)
        had_pick = picks[kind].pop(slot, None) is not None
        if had_pick:
            self._write_picks(picks, overlay_dir)
        return self._remove_slot_files(slot, kind, self.assets_dir(overlay_dir)) > 0 or had_pick

    def _remove_slot_files(self, slot: str, kind: str, folder: Path) -> int:
        exts = IMAGE_EXTS if kind == "image" else SOUND_EXTS
        n = 0
        for ext in exts:
            path = folder / f"{slot}.{ext}"
            if path.is_file():
                try:
                    path.unlink()
                    n += 1
                except OSError as e:
                    log.debug("could not delete %s: %s", path, e)
        return n

    def import_legacy(self, overlay_dir: Optional[Path] = None) -> int:
        """Copy files dropped into assets/<name>/ into the library and point their slots at them
        (only slots with no pick yet). The old files stay, so an older Core still finds them."""
        folder = self.assets_dir(overlay_dir)
        if not folder.is_dir():
            return 0
        picks = self.read_picks(overlay_dir)
        done = 0
        for kind, slots, exts in (("image", self.image_slots, IMAGE_EXTS), ("sound", self.sound_slots, SOUND_EXTS)):
            for slot in slots:
                if slot in picks[kind]:
                    continue
                for ext in exts:
                    path = folder / f"{slot}.{ext}"
                    if not path.is_file():
                        continue
                    try:
                        entry, _ = self.library.save(path.read_bytes(), self._default_name(slot, kind))
                    except (OSError, ValueError) as e:
                        log.warning("Couldn't move %s into the file library: %s", path, e)
                        break
                    if (entry["kind"] == "sound") == (kind == "sound"):
                        picks[kind][slot] = entry["name"]
                        done += 1
                    break
        if done:
            self._write_picks(picks, overlay_dir)
            log.info("Moved %d %s file(s) into the file library (data/media)", done, self.name)
        return done

    # ── shared library hooks (core/media_library.py) ────────
    def media_refs(self, overlay_dir: Optional[Path] = None) -> list[dict[str, str]]:
        """Every slot that uses a library file: [{name, overlay, slot, kind}]."""
        picks = self.read_picks(overlay_dir)
        return [{"name": n, "overlay": self.name, "slot": slot, "kind": kind}
                for kind in ("image", "sound") for slot, n in sorted(picks[kind].items())]

    def media_renamed(self, old: str, new: str, overlay_dir: Optional[Path] = None) -> int:
        picks = self.read_picks(overlay_dir)
        n = 0
        for kind in ("image", "sound"):
            for slot, name in list(picks[kind].items()):
                if name == old:
                    picks[kind][slot] = new
                    n += 1
        if n:
            self._write_picks(picks, overlay_dir)
        return n

    def media_forgotten(self, name: str, overlay_dir: Optional[Path] = None) -> int:
        picks = self.read_picks(overlay_dir)
        n = 0
        for kind in ("image", "sound"):
            for slot, used in list(picks[kind].items()):
                if used == name:
                    del picks[kind][slot]
                    n += 1
        if n:
            self._write_picks(picks, overlay_dir)
        return n
