"""Unique-chatter roster for one stream session.

Persists to a small JSON file so a crash does not wipe the credits list.
Identity is (platform, username) — same person on two platforms is two lines.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from .models import ChatEvent, Chatter

log = logging.getLogger("core.roster")


class Roster:
    def __init__(self, path: Path, ignore: list[str], min_len: int = 1):
        self.path = path
        self.ignore = {n.lower().strip() for n in ignore if n}
        self.min_len = max(0, int(min_len))
        self.started_at = time.time()
        self.chatters: dict[str, Chatter] = {}
        self._dirty = False
        self._on_change: list[Callable] = []

    def on_change(self, fn: Callable) -> None:
        self._on_change.append(fn)

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("failed to read session file %s", self.path)
            return
        self.started_at = float(data.get("started_at") or self.started_at)
        for item in data.get("chatters") or []:
            try:
                c = Chatter.from_dict(item)
                if c.username:
                    self.chatters[c.key] = c
            except Exception:
                continue
        log.info("Loaded session: %s unique chatters", len(self.chatters))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "started_at": self.started_at,
            "saved_at": time.time(),
            "chatters": [c.to_dict() for c in self.chatters.values()],
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False

    def save_if_dirty(self) -> None:
        if self._dirty:
            self.save()

    def reset(self) -> None:
        self.chatters.clear()
        self.started_at = time.time()
        self._dirty = True
        self.save()
        self._notify()
        log.info("Session roster reset")

    def ingest(self, event: ChatEvent) -> Optional[Chatter]:
        user = event.user
        if not user.username:
            return None
        if user.username in self.ignore:
            return None
        msg = (event.message or "").strip()
        if len(msg) < self.min_len:
            return None

        key = f"{event.platform.value}:{user.username}"
        now = event.timestamp or time.time()
        existing = self.chatters.get(key)
        if existing:
            existing.last_seen = now
            existing.messages += 1
            if user.display_name:
                existing.display_name = user.display_name
            if user.color:
                existing.color = user.color
            existing.is_mod = existing.is_mod or user.is_mod
            existing.is_vip = existing.is_vip or user.is_vip
            existing.is_subscriber = existing.is_subscriber or user.is_subscriber
            self._dirty = True
            return None

        chatter = Chatter(
            platform=event.platform.value,
            username=user.username,
            display_name=user.display_name or user.username,
            first_seen=now,
            last_seen=now,
            messages=1,
            color=user.color,
            is_mod=user.is_mod,
            is_vip=user.is_vip,
            is_subscriber=user.is_subscriber,
        )
        self.chatters[key] = chatter
        self._dirty = True
        self._notify()
        log.info("New chatter [%s] %s", chatter.platform, chatter.display_name)
        return chatter

    def _notify(self) -> None:
        for fn in self._on_change:
            try:
                fn()
            except Exception:
                log.exception("roster change callback failed")

    def counts_by_platform(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.chatters.values():
            out[c.platform] = out.get(c.platform, 0) + 1
        return out

    def list_chatters(self, sort: str = "first_seen") -> list[Chatter]:
        items = list(self.chatters.values())
        if sort == "name":
            items.sort(key=lambda c: c.display_name.lower())
        elif sort == "last_seen":
            items.sort(key=lambda c: c.last_seen)
        elif sort == "messages":
            items.sort(key=lambda c: (-c.messages, c.first_seen))
        else:
            items.sort(key=lambda c: c.first_seen)
        return items

    def snapshot(self, sort: str = "first_seen") -> dict:
        items = self.list_chatters(sort)
        return {
            "started_at": self.started_at,
            "count": len(items),
            "by_platform": self.counts_by_platform(),
            "chatters": [c.to_dict() for c in items],
        }
