"""
The small JSON files where the Kick and Twitch adapters remember chatters' picture links
(``data/kick_avatars.json``, ``data/twitch_avatars.json``).

On a busy channel these grow with every new chatter, so:
- entries not refreshed for ``KEEP_SEC`` are dropped, and the file keeps at most
  ``MAX_ENTRIES`` (newest first);
- the file is written at most every ``SAVE_EVERY_SEC`` while chat is running (and once
  more when Core stops), through a temporary file so a crash never leaves half a file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

KEEP_SEC = 60 * 24 * 3600     # forget a chatter's link after 60 days without a refresh
MAX_ENTRIES = 20000
SAVE_EVERY_SEC = 30.0


def prune(cache: dict[str, dict], now: float | None = None,
          keep_sec: float = KEEP_SEC, max_entries: int = MAX_ENTRIES) -> dict[str, dict]:
    """Drop old entries and keep the newest max_entries. Returns a new dict."""
    now = time.time() if now is None else now
    fresh = {k: v for k, v in cache.items() if now - float(v.get("ts") or 0) < keep_sec}
    if len(fresh) > max_entries:
        newest = sorted(fresh.items(), key=lambda kv: float(kv[1].get("ts") or 0), reverse=True)
        fresh = dict(newest[:max_entries])
    return fresh


def write(path: Path, cache: dict[str, dict]) -> None:
    """Write the cache compactly via a temporary file (raises OSError)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
