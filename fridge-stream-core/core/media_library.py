"""
Stored files: one shared library for every picture, video, sound and font uploaded to Core.

A file is uploaded once and used in as many places as wanted. Places keep the file's *name*,
never a copy:
  - alerts overlay: a picture and a sound per alert kind
  - chat overlay: background, badge pictures, message / paid sounds
  - custom CSS: ``url(/media/<name>)`` (no extension needed, so the link survives Replace)

Files live in ``data/media/`` (local, git-ignored) as ``<name>.<ext>``; ``library.json`` next to
them keeps each file's content hash (so an identical re-upload reuses the file) and when it was
added. The type is always read from the file's first bytes (``overlay_style.sniff``), never the
name. Core serves the folder read-only at ``/media/<name>`` and ``/media/<name>.<ext>``.

Places that use files report them through ``media_refs()`` and follow renames / deletes through
``media_renamed()`` / ``media_forgotten()`` (``OverlayStyle`` does this for alerts and chat).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from core.overlay_style import sniff

log = logging.getLogger("core.media_library")

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "media"
INDEX_FILE = "library.json"
URL_PREFIX = "/media/"
MAX_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_FILES = 500
_NAME_RE = re.compile(r"[^a-z0-9_-]+")

# extension (as saved) -> kind
KIND_FOR_EXT = {
    "png": "image", "jpg": "image", "gif": "image", "webp": "image",
    "webm": "video", "mp4": "video",
    "mp3": "sound", "ogg": "sound", "wav": "sound", "m4a": "sound",
    "woff2": "font", "woff": "font", "ttf": "font", "otf": "font",
}
# what a picture slot can show; Replace keeps a file inside its group
GROUP_FOR_KIND = {"image": "picture", "video": "picture", "sound": "sound", "font": "font"}
CONTENT_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "webm": "video/webm", "mp4": "video/mp4",
    "mp3": "audio/mpeg", "ogg": "audio/ogg", "wav": "audio/wav", "m4a": "audio/mp4",
    "woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf", "otf": "font/otf",
}


def clean_name(raw: str) -> str:
    """A file's handle: lowercase letters, numbers, - and _ (max 40)."""
    return _NAME_RE.sub("-", str(raw or "").strip().lower()).strip("-_")[:40]


def name_from_filename(filename: str) -> str:
    """'My Ding!.MP3' -> 'my-ding'."""
    stem = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return clean_name(stem)


def decode_base64(b64: str) -> bytes:
    raw = str(b64 or "")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as e:
        raise ValueError("Couldn't read the upload.") from e


class MediaLibrary:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else DATA_DIR
        self._lock = threading.RLock()

    # ── index ───────────────────────────────────────────────
    def _index_path(self) -> Path:
        return self.root / INDEX_FILE

    def _read_index(self) -> dict[str, dict[str, Any]]:
        path = self._index_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return {}
        files = data.get("files") if isinstance(data, dict) else None
        return {str(k): dict(v) for k, v in files.items() if isinstance(v, dict)} if isinstance(files, dict) else {}

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"files": index}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    # ── lookup ──────────────────────────────────────────────
    def _files(self) -> dict[str, Path]:
        """{name: path} for every library file on disk (one per name; extra copies are ignored)."""
        out: dict[str, Path] = {}
        if not self.root.is_dir():
            return out
        for p in sorted(self.root.iterdir()):
            if not p.is_file() or p.name == INDEX_FILE:
                continue
            ext = p.suffix.lower().lstrip(".")
            name = p.stem
            if ext in KIND_FOR_EXT and name == clean_name(name) and name not in out:
                out[name] = p
        return out

    def path(self, name: str) -> Optional[Path]:
        return self._files().get(clean_name(name)) if name else None

    def _entry(self, name: str, path: Path, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
        ext = path.suffix.lower().lstrip(".")
        try:
            st = path.stat()
            size, mtime = st.st_size, int(st.st_mtime)
        except OSError:
            size, mtime = 0, 0
        meta = index.get(name) or {}
        return {
            "name": name,
            "file": path.name,
            "ext": ext,
            "kind": KIND_FOR_EXT[ext],
            "size": size,
            "added": int(meta.get("added") or mtime),
            "version": mtime,
            "url": f"{URL_PREFIX}{path.name}?v={mtime}",
            "css_url": f"{URL_PREFIX}{name}",
        }

    def get(self, name: str) -> Optional[dict[str, Any]]:
        name = clean_name(name)
        path = self.path(name)
        return self._entry(name, path, self._read_index()) if path else None

    def list(self) -> list[dict[str, Any]]:
        index = self._read_index()
        return [self._entry(n, p, index) for n, p in self._files().items()]

    def url(self, name: str) -> Optional[str]:
        e = self.get(name)
        return e["url"] if e else None

    def resolve(self, file_name: str) -> Optional[Path]:
        """File to serve for ``/media/<name>`` or ``/media/<name>.<anything>`` (the name decides)."""
        raw = str(file_name or "")
        if "/" in raw or "\\" in raw:
            return None
        stem = raw.split(".", 1)[0]
        if not stem or stem != clean_name(stem):
            return None
        return self.path(stem)

    # ── checks ──────────────────────────────────────────────
    @staticmethod
    def check(data: bytes) -> str:
        """Saved extension for an upload, or ValueError with a plain reason."""
        if not data:
            raise ValueError("The file is empty.")
        ext = sniff(data)
        ext = "jpg" if ext == "jpeg" else ext
        if ext not in KIND_FOR_EXT:
            raise ValueError("Core can store pictures (PNG, JPEG, GIF, WebP), videos (WebM, MP4), "
                             "sounds (MP3, OGG, WAV, M4A) and fonts (WOFF2, WOFF, TTF, OTF).")
        limit = MAX_VIDEO_BYTES if KIND_FOR_EXT[ext] == "video" else MAX_BYTES
        if len(data) > limit:
            raise ValueError(f"Too big ({len(data) // 1024} KB). The limit is {limit // (1024 * 1024)} MB.")
        return ext

    def _free_name(self, wanted: str, taken: set[str]) -> str:
        base = clean_name(wanted) or "file"
        if base not in taken:
            return base
        for i in range(2, 1000):
            cand = f"{base[:36]}-{i}"
            if cand not in taken:
                return cand
        return f"{base[:28]}-{int(time.time())}"

    # ── changes ─────────────────────────────────────────────
    def save(self, data: bytes, name: str = "") -> tuple[dict[str, Any], bool]:
        """Store an upload. Returns (entry, reused): an identical file already in the library is
        reused instead of copied. A name that's taken by a different file gets -2, -3, ..."""
        ext = self.check(data)
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            files = self._files()
            index = self._read_index()
            for n, p in files.items():
                meta = index.get(n) or {}
                h = meta.get("sha256")
                if not h:
                    try:
                        h = hashlib.sha256(p.read_bytes()).hexdigest()
                    except OSError:
                        continue
                    index.setdefault(n, {})["sha256"] = h
                if h == digest:
                    return self._entry(n, p, index), True
            if len(files) >= MAX_FILES:
                raise ValueError(f"The library is full ({MAX_FILES} files). Delete some first.")
            final = self._free_name(name, set(files))
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{final}.{ext}"
            self._write_file(path, data)
            index[final] = {"sha256": digest, "added": int(time.time())}
            self._write_index(index)
            return self._entry(final, path, index), False

    def save_exact(self, data: bytes, name: str) -> dict[str, Any]:
        """Store an upload under exactly this name (reaction pictures: img:<name>). The same file
        already under that name is fine; a different file under it is a ValueError. An identical
        file under another name is stored again, because the name is what matters here."""
        ext = self.check(data)
        name = clean_name(name)
        if not name:
            raise ValueError("Give it a name made of letters, numbers, - or _.")
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            files = self._files()
            index = self._read_index()
            have = files.get(name)
            if have is not None:
                h = (index.get(name) or {}).get("sha256") or hashlib.sha256(have.read_bytes()).hexdigest()
                if h == digest:
                    return self._entry(name, have, index)
                raise ValueError(f"There's already a stored file called '{name}'. Pick another name, "
                                 "or use Replace on the Stored files page to change it everywhere.")
            if len(files) >= MAX_FILES:
                raise ValueError(f"The library is full ({MAX_FILES} files). Delete some first.")
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / f"{name}.{ext}"
            self._write_file(path, data)
            index[name] = {"sha256": digest, "added": int(time.time())}
            self._write_index(index)
            return self._entry(name, path, index)

    def save_base64(self, b64: str, name: str = "") -> tuple[dict[str, Any], bool]:
        return self.save(decode_base64(b64), name)

    def replace(self, name: str, data: bytes) -> dict[str, Any]:
        """New content under the same name, so every place using it shows the new file. A picture
        stays a picture or video, a sound a sound, a font a font."""
        name = clean_name(name)
        ext = self.check(data)
        with self._lock:
            old = self.path(name)
            if old is None:
                raise KeyError(name)
            old_kind = KIND_FOR_EXT[old.suffix.lower().lstrip(".")]
            if GROUP_FOR_KIND[old_kind] != GROUP_FOR_KIND[KIND_FOR_EXT[ext]]:
                want = {"picture": "a picture or video", "sound": "a sound", "font": "a font"}[GROUP_FOR_KIND[old_kind]]
                raise ValueError(f"'{name}' is used as {want}, so the new file has to be {want} too.")
            path = self.root / f"{name}.{ext}"
            self._write_file(path, data)
            if old != path:
                try:
                    old.unlink()
                except OSError as e:
                    log.debug("could not delete %s: %s", old, e)
            index = self._read_index()
            meta = index.setdefault(name, {})
            meta["sha256"] = hashlib.sha256(data).hexdigest()
            meta.setdefault("added", int(time.time()))
            self._write_index(index)
            return self._entry(name, path, index)

    def rename(self, name: str, new_name: str) -> dict[str, Any]:
        name, new = clean_name(name), clean_name(new_name)
        if not new:
            raise ValueError("Give it a name made of letters, numbers, - or _.")
        with self._lock:
            files = self._files()
            old = files.get(name)
            if old is None:
                raise KeyError(name)
            if new == name:
                return self.get(name)  # type: ignore[return-value]
            if new in files:
                raise ValueError(f"There's already a file called '{new}'.")
            path = self.root / f"{new}{old.suffix.lower()}"
            old.replace(path)
            index = self._read_index()
            index[new] = index.pop(name, {})
            self._write_index(index)
            return self._entry(new, path, index)

    def delete(self, name: str) -> bool:
        name = clean_name(name)
        with self._lock:
            path = self.path(name)
            if path is None:
                return False
            path.unlink()
            index = self._read_index()
            if index.pop(name, None) is not None:
                self._write_index(index)
            return True

    @staticmethod
    def _write_file(path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)


_DEFAULT: Optional[MediaLibrary] = None


def default_library() -> MediaLibrary:
    """The library in ``data/media`` (one per Core)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = MediaLibrary()
    return _DEFAULT
