"""Images that reactions can throw / drop / float instead of an emoji.

A reaction's object param "img:boot" uses the image named "boot". Images live in
  - overlay/assets/reactions/   built-in, shipped (boot.png)
  - data/reaction_images/       uploaded in Admin → Config → Reactions (local, not in git)
An upload with the same name as a built-in replaces it for this install.

Core serves them at /reactions/images/<file> (read-only, same origin as the overlays) and
puts {"name", "url", "animated"} into the reaction packet's params as `object_image`, so
Stream Rooms and the fallback overlay can draw the picture.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"[^a-z0-9_-]+")
EXT_FOR_KIND = {"png": ".png", "jpeg": ".jpg", "gif": ".gif"}
KIND_FOR_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif"}
URL_PREFIX = "/reactions/images/"
OBJECT_PREFIX = "img:"


def clean_name(raw: str) -> str:
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
    def __init__(self, builtin_dir: Path, custom_dir: Path):
        self.builtin_dir = Path(builtin_dir)
        self.custom_dir = Path(custom_dir)

    # ── lookup ─────────────────────────────────────────────────
    def _scan(self, folder: Path, source: str) -> Dict[str, Dict[str, Any]]:
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

    def all(self) -> Dict[str, Dict[str, Any]]:
        found = self._scan(self.builtin_dir, "built-in")
        found.update(self._scan(self.custom_dir, "custom"))     # uploads win
        return found

    def list(self) -> List[Dict[str, Any]]:
        return [{k: v for k, v in info.items() if k != "path"} for info in self.all().values()]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
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

    # ── changes (custom folder only) ───────────────────────────
    def save(self, name: str, data: bytes) -> Dict[str, Any]:
        name = clean_name(name)
        if not name:
            raise ValueError("Give the image a name (letters, numbers, - or _).")
        if not data:
            raise ValueError("The file is empty.")
        if len(data) > MAX_BYTES:
            raise ValueError(f"Too big ({len(data) // 1024} KB). The limit is {MAX_BYTES // (1024 * 1024)} MB.")
        kind = sniff(data)
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
        raw = str(b64 or "")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception as e:
            raise ValueError("Couldn't read the upload.") from e
        return self.save(name, data)

    def delete(self, name: str) -> bool:
        """Deletes an upload. Built-in images can't be deleted (an upload of the same
        name only hides them)."""
        name = clean_name(name)
        gone = False
        for p in self.custom_dir.glob(name + ".*") if self.custom_dir.is_dir() else []:
            if KIND_FOR_EXT.get(p.suffix.lower()):
                p.unlink()
                gone = True
        return gone
