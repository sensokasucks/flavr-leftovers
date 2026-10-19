"""
Kick chatter profile pictures.

Kick's chat events don't carry the sender's picture, so the first time someone
chats we look their channel up once (``/api/v2/channels/{slug}`` -> ``user.profile_pic``)
and remember the answer in ``data/kick_avatars.json`` (runtime state, git-ignored).
The chat message goes out right away; when the lookup finishes, the adapter
publishes a ``user_update`` so overlays / Stream Rooms can fill the picture in.

Kick / Cloudflare sometimes answers 403 or 429. Those users are retried after
``RETRY_SEC`` instead of hammering the API. Toggle: ``kick.avatars`` (default on).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from adapters import avatar_link_file

log = logging.getLogger("adapters.kick_avatars")

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "kick_avatars.json"
RETRY_SEC = 10 * 60              # seconds before a failed lookup (403 / 429 / error) is tried again
REFRESH_SEC = 3 * 24 * 3600      # one lookup per chatter and Kick sometimes refuses, so re-check less often
MAX_PARALLEL = 2                 # lookups running at once, to stay under Kick's rate limits

# (slug) -> (status, url): status 200 = found (url may be "" for no picture), other = failed
Fetcher = Callable[[str], Awaitable[tuple[int, str]]]
Found = Callable[[str], Awaitable[None]]


def picture_from_channel(data: dict) -> str:
    """``/api/v2/channels/{slug}`` JSON -> profile picture URL ("" when the user has none)."""
    user = data.get("user") if isinstance(data, dict) else None
    if isinstance(user, dict):
        pic = user.get("profile_pic") or user.get("profilepic") or ""
        return str(pic) if pic else ""
    return ""


class KickAvatars:
    """Cache of Kick chatter pictures, owned by KickAdapter (adapters/kick.py).

    ``fetcher`` and ``path`` can be swapped in tests so no network or real file is used.
    """

    def __init__(self, enabled: bool = True, fetcher: Optional[Fetcher] = None,
                 path: Optional[Path] = None):
        self.enabled = enabled
        self._fetch = fetcher or self._fetch_http
        self._path = path or DATA_PATH
        self._cache: dict[str, dict] = {}     # slug -> {"url": str, "ts": float}
        self._failed: dict[str, float] = {}   # slug -> time of last failure
        self._pending: set[str] = set()
        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._tasks: set[asyncio.Task] = set()
        self._dirty = False
        self._last_save = 0.0
        self._load()

    def get(self, slug: str) -> Optional[str]:
        """Known picture URL ("" = no picture), or None if we haven't looked yet. An old link is
        still returned; ``request()`` re-checks it in the background."""
        entry = self._cache.get(slug.lower())
        if entry is None:
            return None
        return str(entry.get("url", ""))

    def request(self, slug: str, on_found: Found) -> None:
        """Look the picture up in the background (new chatter, or a saved link older than
        REFRESH_SEC) and call on_found(url) when there is a picture Core didn't know yet."""
        slug = slug.lower().strip()
        if not self.enabled or not slug or slug in self._pending:
            return
        entry = self._cache.get(slug)
        if entry is not None and time.time() - float(entry.get("ts", 0)) < REFRESH_SEC:
            return
        if time.time() - self._failed.get(slug, 0.0) < RETRY_SEC:
            return
        self._pending.add(slug)
        task = asyncio.create_task(self._lookup(slug, on_found), name=f"kick-avatar-{slug}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def stop(self) -> None:
        """Cancel lookups still running and write the cache (called when the adapter stops)."""
        for t in list(self._tasks):
            t.cancel()
        self.save()

    def save(self) -> None:
        """Write the cache to disk now if it changed (errors are only logged at DEBUG)."""
        if not self._dirty:
            return
        try:
            self._cache = avatar_link_file.prune(self._cache)
            avatar_link_file.write(self._path, self._cache)
            self._dirty = False
            self._last_save = time.monotonic()
        except OSError as e:
            log.debug("could not save %s: %s", self._path, e)

    def save_soon(self) -> None:
        """Save, but at most every few seconds while chat is busy (stop() saves the rest)."""
        if time.monotonic() - self._last_save >= avatar_link_file.SAVE_EVERY_SEC or not self._last_save:
            self.save()

    # ── private ─────────────────────────────────────────────
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache = avatar_link_file.prune(
                    {str(k): v for k, v in data.items() if isinstance(v, dict)})
        except (OSError, ValueError):
            self._cache = {}

    async def _lookup(self, slug: str, on_found: Found) -> None:
        try:
            async with self._sem:
                status, url = await self._fetch(slug)
            if status != 200:
                self._failed[slug] = time.time()
                return
            before = (self._cache.get(slug) or {}).get("url")
            self._cache[slug] = {"url": url, "ts": time.time()}
            self._dirty = True
            self.save_soon()
            # a re-check that finds the same link changes nothing on screen
            if url and url != before:
                await on_found(url)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._failed[slug] = time.time()
            log.debug("Kick avatar lookup for %s failed: %s", slug, e)
        finally:
            self._pending.discard(slug)

    @staticmethod
    async def _fetch_http(slug: str) -> tuple[int, str]:
        """Default fetcher: ask Kick's public channel API, with browser-like headers for Cloudflare."""
        # imported here so tests that pass their own fetcher don't need httpx or the Kick adapter
        import httpx
        from adapters.kick import BROWSER_HEADERS

        async with httpx.AsyncClient(timeout=10.0, headers=BROWSER_HEADERS, follow_redirects=True) as client:
            r = await client.get(f"https://kick.com/api/v2/channels/{slug}")
            if r.status_code != 200:
                return r.status_code, ""
            return 200, picture_from_channel(r.json())
