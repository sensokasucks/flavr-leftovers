"""
Chatter profile pictures, kept by Core so every overlay (and Stream Rooms) can use them.

The adapters find each chatter's picture *link* (Kick channel lookup, Twitch Helix,
YouTube author photo). This store downloads each picture once, turns it into a
128 px square PNG (when Pillow is installed; otherwise the original file is kept) and
saves it under ``data/avatars/<platform>/<id>.<ext>`` (runtime state, git-ignored).
Overlays load it from Core itself (``/avatars/<platform>/<file>``), so pictures keep
working when a platform's CDN refuses hot-linking, and Stream Rooms gets a clean PNG
(Redot's JPEG loader trips over some Twitch JPEGs).

``data/avatars/index.json`` remembers, per chatter, the source link, the file, when it
was fetched and the chatter's login / display name (for the by-name lookup that
overlays like reactions or credits can use).

Config (``avatars:`` in config.yaml):
  save_local: true      download and serve pictures from Core (false = link only)
  hide: []              names whose picture is never shown anywhere ("kick:name" = one platform)
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional
from urllib.parse import urlparse

log = logging.getLogger("core.avatar_store")

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "avatars"
SIZE = 128
MAX_BYTES = 3 * 1024 * 1024
REFRESH_SEC = 7 * 24 * 3600      # re-download weekly, like the link caches
RETRY_SEC = 10 * 60              # after a failed download
MAX_PARALLEL = 3
PLATFORMS = ("kick", "twitch", "youtube")
_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")

# (url) -> (status, bytes)
Fetcher = Callable[[str], Awaitable[tuple[int, bytes]]]
# (platform, user id, local url) -> None, called when a picture file is ready
Ready = Callable[[str, str, str], Awaitable[None]]


def safe_id(user_id: str) -> str:
    """User id -> a file name part (YouTube channel ids and Kick ids are already safe)."""
    s = _ID_RE.sub("_", str(user_id or "").strip())[:80]
    return s or "_"


def sniff(body: bytes) -> str:
    """Picture type from the first bytes: png / jpg / gif / webp, or ""."""
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if body[:3] == b"\xff\xd8\xff":
        return "jpg"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    return ""


def to_png(body: bytes, size: int = SIZE) -> Optional[bytes]:
    """Centre-crop to a square, resize to size x size, PNG. None if Pillow is missing or can't read it."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(body)) as im:
            im.seek(0)                           # animated: first frame
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGBA")
            im = ImageOps.fit(im, (size, size), method=Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception as e:
        log.debug("could not convert picture: %s", e)
        return None


def allowed_url(url: str) -> bool:
    """Only https links to public hosts (the links come from chat platforms, never from viewers)."""
    try:
        u = urlparse(str(url or ""))
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname:
        return False
    host = u.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        return True


def parse_hide(entries: Iterable[Any]) -> list[tuple[str, str]]:
    """["name", "kick:name", "@name"] -> [(platform or "", name)], lower case."""
    out: list[tuple[str, str]] = []
    for raw in entries or []:
        s = str(raw or "").strip().lower()
        if not s:
            continue
        plat = ""
        if ":" in s:
            p, rest = s.split(":", 1)
            p = {"yt": "youtube"}.get(p.strip(), p.strip())
            if p in PLATFORMS:
                plat, s = p, rest.strip()
        s = s.lstrip("@").strip()
        if s and (plat, s) not in out:
            out.append((plat, s))
    return out


class AvatarStore:
    def __init__(self, root: Optional[Path] = None, fetcher: Optional[Fetcher] = None,
                 save_local: bool = True, hide: Iterable[Any] = ()):
        self.root = root or DATA_DIR
        self.save_local = save_local
        self._fetch = fetcher or self._fetch_http
        self._hide = parse_hide(hide)
        self._index: dict[str, dict] = {}       # "platform:id" -> {url, file, ts, login, name}
        self._failed: dict[str, float] = {}
        self._pending: set[str] = set()
        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._tasks: set[asyncio.Task] = set()
        self._dirty = False
        self._load()

    # ── settings ────────────────────────────────────────────
    def configure(self, cfg: dict) -> None:
        cfg = cfg if isinstance(cfg, dict) else {}
        self.save_local = bool(cfg.get("save_local", True))
        self._hide = parse_hide(cfg.get("hide") or [])

    @property
    def hide_list(self) -> list[str]:
        return [f"{p}:{n}" if p else n for p, n in self._hide]

    def is_hidden(self, platform: str, *names: str) -> bool:
        plat = str(platform or "").lower()
        wanted = {str(n or "").strip().lstrip("@").lower() for n in names if n}
        wanted.discard("")
        for p, n in self._hide:
            if (not p or p == plat) and n in wanted:
                return True
        return False

    # ── lookups ─────────────────────────────────────────────
    def local_url(self, platform: str, user_id: str) -> str:
        """``/avatars/<platform>/<file>?v=<time>`` when Core has the picture, else ""."""
        entry = self._index.get(f"{platform}:{user_id}")
        if not entry or not self.save_local:
            return ""
        name = str(entry.get("file") or "")
        if not name or not (self.root / platform / name).is_file():
            return ""
        return f"/avatars/{platform}/{name}?v={int(float(entry.get('ts') or 0))}"

    def find(self, name: str, platform: str = "") -> Optional[dict]:
        """A chatter by login or display name (case-insensitive, "@" ignored), newest first."""
        n = str(name or "").strip().lstrip("@").lower()
        plat = str(platform or "").strip().lower()
        if not n:
            return None
        best: Optional[tuple[float, str, dict]] = None
        for key, entry in self._index.items():
            p, uid = key.split(":", 1)
            if plat and p != plat:
                continue
            names = {str(entry.get("login") or "").lstrip("@").lower(), str(entry.get("name") or "").lstrip("@").lower()}
            if n not in names:
                continue
            if self.is_hidden(p, *names):
                return None
            ts = float(entry.get("ts") or 0)
            if best is None or ts > best[0]:
                best = (ts, key, entry)
        if best is None:
            return None
        p, uid = best[1].split(":", 1)
        return {"platform": p, "id": uid, "username": best[2].get("login") or "",
                "display_name": best[2].get("name") or "", "profile_image_url": best[2].get("url") or "",
                "avatar_local": self.local_url(p, uid)}

    def entry(self, platform: str, user_id: str) -> dict:
        """What Core knows about a chatter's picture: {url, file, ts, login, name} or {}."""
        return dict(self._index.get(f"{platform}:{user_id}") or {})

    def known_users(self) -> list[dict]:
        out = []
        for key, entry in self._index.items():
            p, uid = key.split(":", 1)
            out.append({"platform": p, "id": uid, "login": entry.get("login") or "", "name": entry.get("name") or ""})
        return out

    def file_path(self, platform: str, file_name: str) -> Optional[Path]:
        """The picture file for the /avatars route, or None (also refuses odd names)."""
        if platform not in PLATFORMS or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", file_name or "") or ".." in file_name:
            return None
        path = self.root / platform / file_name
        return path if path.is_file() else None

    # ── downloads ───────────────────────────────────────────
    def note(self, platform: str, user_id: str, url: str, login: str = "", name: str = "",
             on_ready: Optional[Ready] = None) -> None:
        """A chatter's picture link is known: remember their names and fetch the picture
        in the background if Core doesn't have this version yet."""
        platform = str(platform or "").lower()
        user_id = str(user_id or "").strip()
        if platform not in PLATFORMS or not user_id:
            return
        key = f"{platform}:{user_id}"
        entry = self._index.get(key)
        if entry is not None and (login or name):
            if (login and entry.get("login") != login) or (name and entry.get("name") != name):
                entry["login"] = login or entry.get("login") or ""
                entry["name"] = name or entry.get("name") or ""
                self._dirty = True
        if not url or not self.save_local or key in self._pending or not allowed_url(url):
            return
        if entry is not None and entry.get("url") == url and entry.get("file") \
                and time.time() - float(entry.get("ts") or 0) < REFRESH_SEC \
                and (self.root / platform / str(entry["file"])).is_file():
            return
        if time.time() - self._failed.get(key, 0.0) < RETRY_SEC:
            return
        self._pending.add(key)
        try:
            task = asyncio.get_running_loop().create_task(
                self._download(platform, user_id, url, login, name, on_ready), name=f"avatar-{key}")
        except RuntimeError:
            self._pending.discard(key)
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Tests: wait until the downloads in flight are done."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        self.save()

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / "index.json.tmp"
            tmp.write_text(json.dumps(self._index), encoding="utf-8")
            tmp.replace(self.root / "index.json")
            self._dirty = False
        except OSError as e:
            log.debug("could not save avatar index: %s", e)

    # ── private ─────────────────────────────────────────────
    def _load(self) -> None:
        try:
            data = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._index = {str(k): v for k, v in data.items() if isinstance(v, dict) and ":" in str(k)}
        except (OSError, ValueError):
            self._index = {}

    async def _download(self, platform: str, user_id: str, url: str, login: str, name: str,
                        on_ready: Optional[Ready]) -> None:
        key = f"{platform}:{user_id}"
        try:
            async with self._sem:
                status, body = await self._fetch(url)
            if status != 200 or not body or len(body) > MAX_BYTES or not sniff(body):
                self._failed[key] = time.time()
                return
            # Pillow and the disk work run in a worker thread: a raid brings hundreds of
            # new pictures at once and the event loop must keep reading chat
            file_name = await asyncio.to_thread(self._store_file, platform, user_id, body)
            old = self._index.get(key) or {}
            self._index[key] = {"url": url, "file": file_name, "ts": time.time(),
                                "login": login or old.get("login") or "", "name": name or old.get("name") or ""}
            self._dirty = True
            if len(self._pending) <= 1:
                self.save()
            if on_ready is not None:
                await on_ready(platform, user_id, self.local_url(platform, user_id))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._failed[key] = time.time()
            log.debug("avatar download for %s failed: %s", key, e)
        finally:
            self._pending.discard(key)

    def _store_file(self, platform: str, user_id: str, body: bytes) -> str:
        """Convert and write one picture (runs in a worker thread). Returns the file name."""
        png = to_png(body)
        data, ext = (png, "png") if png else (body, sniff(body))
        folder = self.root / platform
        folder.mkdir(parents=True, exist_ok=True)
        stem = safe_id(user_id)
        file_name = f"{stem}.{ext}"
        for old in folder.glob(f"{stem}.*"):
            if old.name != file_name:
                try:
                    old.unlink()
                except OSError:
                    pass
        (folder / file_name).write_bytes(data)
        return file_name

    @staticmethod
    async def _fetch_http(url: str) -> tuple[int, bytes]:
        import httpx

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 FridgeStreamCore"}) as client:
            async with client.stream("GET", url) as r:
                if r.status_code != 200:
                    return r.status_code, b""
                chunks = []
                total = 0
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        return 413, b""
                    chunks.append(chunk)
                return 200, b"".join(chunks)
