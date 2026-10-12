"""
Per-key cooldowns ("this reaction / signal fired less than N seconds ago").

Keys are strings built with ``CooldownGate.key(...)``. Used by chat reactions; Gamer Stonks
(the market plugin) keeps its own copy for game signals.
"""

from __future__ import annotations

import time
from typing import Any


def _now() -> float:
    return time.time()


class CooldownGate:
    """
    Optional per-key cooldown.

    Keys are tuples like ("rule:streamer-death", "FACT") or
    ("signal:player_death", "book:factorio"). cooldown_sec <= 0 means
    "no cooldown" (always allowed).
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    @staticmethod
    def key(*parts: Any) -> str:
        return "|".join(str(p) for p in parts if p is not None and str(p) != "")

    def remaining(self, key: str, cooldown_sec: float | None) -> float:
        cd = float(cooldown_sec or 0)
        if cd <= 0:
            return 0.0
        last = self._last.get(key, 0.0)
        left = cd - (_now() - last)
        return left if left > 0 else 0.0

    def allow(self, key: str, cooldown_sec: float | None) -> bool:
        return self.remaining(key, cooldown_sec) <= 0

    def touch(self, key: str) -> None:
        self._last[key] = _now()

    def try_acquire(self, key: str, cooldown_sec: float | None) -> bool:
        if not self.allow(key, cooldown_sec):
            return False
        self.touch(key)
        return True

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._last.clear()
        else:
            self._last.pop(key, None)
