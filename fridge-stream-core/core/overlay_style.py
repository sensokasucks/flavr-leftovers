"""
The look of an overlay page, kept next to the page itself (alerts, chat).

Each styled overlay has three things in ``overlay/``:
  - ``<name>-custom.css``: the streamer's own CSS, pasted in the dashboard (or copied from a
    Streamlabs / StreamElements / OBS "Custom CSS" box; the pages use those tools' ids and
    classes so packs drop in).
  - ``<name>-settings.json``: skin, a css_version stamp the page polls so a save applies live,
    and small options (hide messages after N s, sound volume, ...).
  - ``assets/<name>/``: pictures, videos and sounds by slot name (``follow.gif``, ``raid.webm``,
    ``message.mp3``, ``badge-mod.png``). Uploaded from the dashboard or dropped in by hand;
    the page gets the list of what exists so it never probes for missing files.

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

log = logging.getLogger("core.overlay_style")

OVERLAY_DIR = Path(__file__).resolve().parent.parent / "overlay"
MAX_CUSTOM_CSS_BYTES = 256_000
MAX_ASSET_BYTES = 15 * 1024 * 1024
_CSS_BLOCK = re.compile(r"<\s*/?\s*script|<\s*/?\s*style|javascript:|expression\s*\(", re.IGNORECASE)
_SLOT_RE = re.compile(r"[^a-z0-9_-]+")

# preference order when several formats of one slot exist (video first, as the alerts always did)
IMAGE_EXTS = ("webm", "gif", "webp", "png", "jpg", "jpeg", "svg")
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
        return "m4a"
    return None


def clean_slot(raw: str) -> str:
    return _SLOT_RE.sub("-", str(raw or "").strip().lower()).strip("-_")[:40]


class OverlayStyle:
    def __init__(self, name: str, skins: tuple[str, ...], image_slots: tuple[str, ...] = (),
                 sound_slots: tuple[str, ...] = (), options: Optional[dict[str, Any]] = None,
                 ranges: Optional[dict[str, tuple[float, float]]] = None, overlay_dir: Optional[Path] = None):
        self.name = name
        self.skins = skins
        self.image_slots = image_slots
        self.sound_slots = sound_slots
        self.default_options = dict(options or {})
        self.ranges = dict(ranges or {})
        self.overlay_dir = overlay_dir or OVERLAY_DIR

    # ── paths ───────────────────────────────────────────────
    def _root(self, overlay_dir: Optional[Path]) -> Path:
        return overlay_dir or self.overlay_dir

    def css_path(self, overlay_dir: Optional[Path] = None) -> Path:
        return self._root(overlay_dir) / f"{self.name}-custom.css"

    def settings_path(self, overlay_dir: Optional[Path] = None) -> Path:
        return self._root(overlay_dir) / f"{self.name}-settings.json"

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
        return {"skin": skin, "css_version": css_version, "options": options, "media": media, "sounds": sounds}

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
        path = self.settings_path(overlay_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.read_settings(overlay_dir)

    # ── custom CSS ──────────────────────────────────────────
    def read_css(self, overlay_dir: Optional[Path] = None) -> str:
        path = self.css_path(overlay_dir)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def write_css(self, css: str, overlay_dir: Optional[Path] = None) -> dict[str, Any]:
        if not isinstance(css, str):
            raise ValueError("css must be a string")
        raw = css.replace("\r\n", "\n")
        if len(raw.encode("utf-8")) > MAX_CUSTOM_CSS_BYTES:
            raise ValueError("Custom CSS is too large (max 256 KB)")
        if _CSS_BLOCK.search(raw):
            raise ValueError("Custom CSS cannot contain script/style tags or expressions")
        path = self.css_path(overlay_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return self.write_settings(bump_css=True, overlay_dir=overlay_dir)

    # ── assets (pictures, videos, sounds) ───────────────────
    def list_assets(self, overlay_dir: Optional[Path] = None) -> tuple[dict[str, str], dict[str, str]]:
        """({image slot: url}, {sound slot: url}) for the files that exist, relative to the overlay page."""
        folder = self.assets_dir(overlay_dir)
        media: dict[str, str] = {}
        sounds: dict[str, str] = {}
        if not folder.is_dir():
            return media, sounds
        for slot in self.image_slots:
            for ext in IMAGE_EXTS:
                if (folder / f"{slot}.{ext}").is_file():
                    media[slot] = f"assets/{self.name}/{slot}.{ext}"
                    break
        for slot in self.sound_slots:
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

    def save_asset(self, slot: str, data: bytes, overlay_dir: Optional[Path] = None) -> str:
        """Store an upload for a slot; the old file of that slot (any format) is replaced. Returns the url."""
        slot = clean_slot(slot)
        if self.slot_kind(slot) is None:
            raise ValueError(f"Unknown slot '{slot}'.")
        if not data:
            raise ValueError("The file is empty.")
        if len(data) > MAX_ASSET_BYTES:
            raise ValueError(f"Too big ({len(data) // 1024} KB). The limit is {MAX_ASSET_BYTES // (1024 * 1024)} MB.")
        ext = sniff(data)
        kind = self.slot_kind(slot, ext)
        if kind == "image" and ext not in ("png", "jpeg", "gif", "webp", "webm"):
            raise ValueError("Pictures must be PNG, JPEG, GIF, WebP or WebM video.")
        if kind == "sound" and ext not in ("mp3", "ogg", "wav", "m4a"):
            raise ValueError("Sounds must be MP3, OGG, WAV or M4A.")
        ext = "jpg" if ext == "jpeg" else ext
        folder = self.assets_dir(overlay_dir)
        folder.mkdir(parents=True, exist_ok=True)
        self._remove_slot_files(slot, kind, folder)
        path = folder / f"{slot}.{ext}"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return f"assets/{self.name}/{slot}.{ext}"

    def save_asset_base64(self, slot: str, b64: str, overlay_dir: Optional[Path] = None) -> str:
        raw = str(b64 or "")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception as e:
            raise ValueError("Couldn't read the upload.") from e
        return self.save_asset(slot, data, overlay_dir)

    def delete_asset(self, slot: str, kind: Optional[str] = None, overlay_dir: Optional[Path] = None) -> bool:
        """Remove a slot's file. ``kind`` ("image" / "sound") matters for slots that take both."""
        slot = clean_slot(slot)
        if kind not in ("image", "sound"):
            kind = self.slot_kind(slot)
        if kind is None or self.slot_kind(slot) is None:
            return False
        if kind == "sound" and slot not in self.sound_slots:
            return False
        if kind == "image" and slot not in self.image_slots:
            return False
        return self._remove_slot_files(slot, kind, self.assets_dir(overlay_dir)) > 0

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
