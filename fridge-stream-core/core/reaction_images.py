"""Images that reactions can throw / drop / float instead of an emoji.

A reaction's object param "img:boot" uses the picture named "boot". Pictures come from
  - overlay/assets/reactions/   built-in, shipped (boot.png); served at /reactions/images/<file>
  - data/reaction_images/       older uploads, before Stored files; copied into Stored files at
                                start (import_legacy) and removed here once they are
  - Stored files                (core/media_library.py, data/media/, /media/<file>): any stored
                                PNG / JPEG / GIF / WebP picture, by its name
Later ones win, so a stored picture called "boot" replaces the built-in for this install.

Core puts {"name", "url", "animated"} into the reaction packet's params as `object_image`, so
Stream Rooms and the fallback overlay can draw the picture.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("core.reaction_images")

# Upload limit in bytes (stricter than Stored files' own limit). URL_PREFIX is where Core serves
# the built-in and old upload folders; OBJECT_PREFIX marks a picture in a reaction's object param.
MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"[^a-z0-9_-]+")
EXT_FOR_KIND = {"png": ".png", "jpeg": ".jpg", "gif": ".gif"}
KIND_FOR_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif"}
URL_PREFIX = "/reactions/images/"
OBJECT_PREFIX = "img:"


def clean_name(raw: str) -> str:
    """A picture's name: lowercase letters, numbers, - and _ (max 40)."""
    name = NAME_RE.sub("-", str(raw or "").strip().lower()).strip("-_")
    return name[:40]


def sniff(data: bytes) -> Optional[str]:
    """png / jpeg / gif from the file's first bytes (never trust the extension)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


class ReactionImages:
    """Finds the pictures a reaction can use, by name. Owned by the ReactionEngine (core/reactions.py).

    ``builtin_dir`` = overlay/assets/reactions, ``custom_dir`` = data/reaction_images.
    """
    def __init__(self, builtin_dir: Path, custom_dir: Path, library: Any = None):
        self.builtin_dir = Path(builtin_dir)
        self.custom_dir = Path(custom_dir)
        self.library = library        # core.media_library.MediaLibrary (Stored files); None = none

    # ── lookup ─────────────────────────────────────────────────
    def _scan(self, folder: Path, source: str) -> Dict[str, Dict[str, Any]]:
        """{name: info} for the PNG / JPEG / GIF files in one folder, tagged with ``source``."""
        out: Dict[str, Dict[str, Any]] = {}
        if not folder.is_dir():
            return out
        for p in sorted(folder.iterdir()):
            kind = KIND_FOR_EXT.get(p.suffix.lower())
            if not kind or not p.is_file():
                continue
            name = clean_name(p.stem)
            if not name:
                continue
            st = p.stat()
            out[name] = {
                "name": name,
                "file": p.name,
                "kind": kind,
                "bytes": st.st_size,
                "source": source,
                "path": p,
                "url": f"{URL_PREFIX}{p.name}?v={int(st.st_mtime)}",
                "animated": kind == "gif",
            }
        return out

    def _stored(self) -> Dict[str, Dict[str, Any]]:
        """{name: info} for the pictures in Stored files (same shape as ``_scan``, ``path`` None)."""
        out: Dict[str, Dict[str, Any]] = {}
        if self.library is None:
            return out
        for f in self.library.list():
            if f["kind"] != "image":          # pictures only (no videos, sounds, fonts)
                continue
            out[f["name"]] = {
                "name": f["name"],
                "file": f["file"],
                "kind": "jpeg" if f["ext"] == "jpg" else f["ext"],
                "bytes": f["size"],
                "source": "stored",
                "path": None,
                "url": f["url"],
                "animated": f["ext"] == "gif",
            }
        return out

    def all(self) -> Dict[str, Dict[str, Any]]:
        """Every usable picture by name; when two share a name the later source wins."""
        found = self._scan(self.builtin_dir, "built-in")
        found.update(self._scan(self.custom_dir, "custom"))     # uploads win
        found.update(self._stored())                            # Stored files win over both
        return found

    def list(self) -> List[Dict[str, Any]]:
        """``all()`` for the API, without the local file paths."""
        return [{k: v for k, v in info.items() if k != "path"} for info in self.all().values()]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Info for one picture name, or None."""
        return self.all().get(clean_name(name))

    def file_path(self, file_name: str) -> Optional[Path]:
        """Resolve a served file name (no directories) to a real file, custom first."""
        fn = Path(str(file_name or "")).name
        if not fn or fn != file_name or KIND_FOR_EXT.get(Path(fn).suffix.lower()) is None:
            return None
        for folder in (self.custom_dir, self.builtin_dir):
            p = folder / fn
            if p.is_file():
                return p
        return None

    def resolve_object(self, value: Any) -> Optional[Dict[str, Any]]:
        """object param "img:boot" -> {name, url, animated}; anything else -> None."""
        text = str(value or "").strip()
        if not text.lower().startswith(OBJECT_PREFIX):
            return None
        info = self.get(text[len(OBJECT_PREFIX):])
        if not info:
            return None
        return {"name": info["name"], "url": info["url"], "animated": info["animated"]}

    # ── changes ────────────────────────────────────────────────
    def save(self, name: str, data: bytes) -> Dict[str, Any]:
        """Store an upload in Stored files under exactly this name (so img:<name> works).
        Without Stored files (tests, old callers) it goes to the old uploads folder."""
        name = clean_name(name)
        if not name:
            raise ValueError("Give the image a name (letters, numbers, - or _).")
        if not data:
            raise ValueError("The file is empty.")
        if len(data) > MAX_BYTES:
            raise ValueError(f"Too big ({len(data) // 1024} KB). The limit is {MAX_BYTES // (1024 * 1024)} MB.")
        kind = sniff(data)
        if self.library is not None:
            from core.overlay_style import sniff as sniff_any

            if kind is None and sniff_any(data) != "webp":
                raise ValueError("Only PNG, JPEG, GIF or WebP images.")
            self.library.save_exact(data, name)
            info = self.get(name) or {}
            return {k: v for k, v in info.items() if k != "path"}
        if kind is None:
            raise ValueError("Only PNG, JPEG or GIF images.")
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        for old in self.custom_dir.glob(name + ".*"):          # replacing: drop the other formats
            if KIND_FOR_EXT.get(old.suffix.lower()):
                old.unlink()
        path = self.custom_dir / (name + EXT_FOR_KIND[kind])
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        info = self.get(name) or {}
        return {k: v for k, v in info.items() if k != "path"}

    def save_base64(self, name: str, b64: str) -> Dict[str, Any]:
        """``save`` for an upload sent as base64 text (a data: url prefix is allowed)."""
        raw = str(b64 or "")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception as e:
            raise ValueError("Couldn't read the upload.") from e
        return self.save(name, data)

    def delete(self, name: str) -> bool:
        """Deletes an older upload from data/reaction_images. Built-in images can't be deleted;
        stored pictures are deleted on the Stored files page (they may be used elsewhere)."""
        name = clean_name(name)
        gone = False
        for p in self.custom_dir.glob(name + ".*") if self.custom_dir.is_dir() else []:
            if KIND_FOR_EXT.get(p.suffix.lower()):
                p.unlink()
                gone = True
        return gone

    def import_legacy(self) -> int:
        """Copy data/reaction_images/* into Stored files under the same names and remove the
        originals that made it. A name Stored files already uses for a different file stays
        here (still usable; the stored one wins) and is logged."""
        if self.library is None or not self.custom_dir.is_dir():
            return 0
        moved = 0
        for p in sorted(self.custom_dir.iterdir()):
            if not p.is_file() or KIND_FOR_EXT.get(p.suffix.lower()) is None:
                continue
            name = clean_name(p.stem)
            if not name:
                continue
            try:
                self.library.save_exact(p.read_bytes(), name)
            except (OSError, ValueError) as e:
                log.warning("Reaction picture %s stays in %s: %s", p.name, self.custom_dir, e)
                continue
            try:
                p.unlink()
            except OSError as e:
                log.debug("could not remove %s: %s", p, e)
            moved += 1
        if moved:
            log.info("Moved %d reaction picture(s) into Stored files (data/media)", moved)
        return moved
