"""
Twitch chatter profile pictures.

Twitch chat (IRC) never carries the sender's picture; only the Helix ``GET /users``
API has it, and that needs a token (see ``twitch_auth.py``: the streamer's sign-in, or an
app token when someone configured their own app with a secret). The first time a chatter
speaks, their user id is queued; a moment later one request looks up everyone queued
(up to 100 ids per call) and the answers are kept in ``data/twitch_avatars.json``
(runtime state, git-ignored). The chat message goes out right away; when the lookup
finishes, the adapter publishes a ``user_update`` so overlays / Stream Rooms fill the
picture in.

Twin of ``kick_avatars.py``. Toggle: ``twitch.avatars`` (default on). Without a token the
module simply does nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

log = logging.getLogger("adapters.twitch_avatars")

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "twitch_avatars.json"
USERS_URL = "https://api.twitch.tv/helix/users"
RETRY_SEC = 10 * 60
REFRESH_SEC = 7 * 24 * 3600      # pictures change rarely; re-check weekly
BATCH_DELAY_SEC = 0.5            # gather ids for this long, then one request
BATCH_MAX = 100                  # Helix limit per call

# (user ids) -> (status, {id: picture url}); status 200 = answered (missing ids = no picture)
Fetcher = Callable[[list[str]], Awaitable[tuple[int, dict[str, str]]]]
Found = Callable[[str], Awaitable[None]]


def pictures_from_users(data: dict) -> dict[str, str]:
    """Helix ``GET /users`` JSON -> {user id: profile_image_url}."""
    out: dict[str, str] = {}
    rows = data.get("data") if isinstance(data, dict) else None
    for row in rows or []:
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = str(row.get("profile_image_url") or "")
    return out


class TwitchAvatars:
    def __init__(self, enabled: bool = True, fetcher: Optional[Fetcher] = None,
                 path: Optional[Path] = None, auth=None, batch_delay: float = BATCH_DELAY_SEC):
        self.enabled = enabled
        self._auth = auth
        self._fetch = fetcher or self._fetch_http
        self._path = path or DATA_PATH
        self._delay = batch_delay
        self._cache: dict[str, dict] = {}     # user id -> {"url": str, "ts": float}
        self._failed: dict[str, float] = {}   # user id -> time of last failure
        self._queue: dict[str, Found] = {}    # ids waiting for the next batch
        self._pending: set[str] = set()       # queued or in flight
        self._flush_task: Optional[asyncio.Task] = None
        self._tasks: set[asyncio.Task] = set()
        self._dirty = False
        self._load()

    def get(self, user_id: str) -> Optional[str]:
        """Known picture URL ("" = no picture), or None if we haven't looked yet."""
        entry = self._cache.get(str(user_id))
        if entry is None or time.time() - float(entry.get("ts", 0)) > REFRESH_SEC:
            return None if entry is None else str(entry.get("url", ""))
        return str(entry.get("url", ""))

    def request(self, user_id: str, on_found: Found) -> None:
        """Queue a lookup; the batch goes out after a short delay. Calls on_found(url) if there is a picture."""
        user_id = str(user_id).strip()
        if not self.enabled or not user_id or not user_id.isdigit() or user_id in self._pending:
            return
        entry = self._cache.get(user_id)
        if entry is not None and time.time() - float(entry.get("ts", 0)) < REFRESH_SEC:
            return
        if time.time() - self._failed.get(user_id, 0.0) < RETRY_SEC:
            return
        self._pending.add(user_id)
        self._queue[user_id] = on_found
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_later(), name="twitch-avatars-batch")
            self._tasks.add(self._flush_task)
            self._flush_task.add_done_callback(self._tasks.discard)

    def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        self.save()

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache), encoding="utf-8")
            self._dirty = False
        except OSError as e:
            log.debug("could not save %s: %s", self._path, e)

    # ── private ─────────────────────────────────────────────
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            self._cache = {}

    async def _flush_later(self) -> None:
        try:
            await asyncio.sleep(self._delay)
            while self._queue:
                ids = list(self._queue)[:BATCH_MAX]
                callbacks = {i: self._queue.pop(i) for i in ids}
                await self._lookup(ids, callbacks)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("Twitch avatar batch failed: %s", e)

    async def _lookup(self, ids: list[str], callbacks: dict[str, Found]) -> None:
        now = time.time()
        try:
            status, found = await self._fetch(ids)
            if status == 401 and self._auth is not None:
                # token went stale between checks: refresh once and retry
                self._auth.invalidate()
                status, found = await self._fetch(ids)
            if status != 200:
                for i in ids:
                    self._failed[i] = now
                return
            for i in ids:
                url = found.get(i, "")
                self._cache[i] = {"url": url, "ts": now}
            self._dirty = True
            self.save()
            for i in ids:
                url = found.get(i, "")
                if url:
                    try:
                        await callbacks[i](url)
                    except Exception as e:
                        log.debug("Twitch avatar callback failed: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            for i in ids:
                self._failed[i] = now
            log.debug("Twitch avatar lookup failed: %s", e)
        finally:
            for i in ids:
                self._pending.discard(i)

    async def _fetch_http(self, ids: list[str]) -> tuple[int, dict[str, str]]:
        import httpx

        token = await self._auth.token() if self._auth is not None else None
        if not token:
            return 401 if self._auth is not None and self._auth.connected else 0, {}
        headers = {"Client-Id": self._auth.client_id, "Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(USERS_URL, params=[("id", i) for i in ids], headers=headers)
            if r.status_code != 200:
                return r.status_code, {}
            return 200, pictures_from_users(r.json())
