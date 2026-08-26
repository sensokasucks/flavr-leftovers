"""Viewer / CPM / command-rate metrics and weighted power level."""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Optional

from .models import MetricsSnapshot, Platform


class MetricsAggregator:
    def __init__(self, config: dict | None = None) -> None:
        cfg = (config or {}).get("metrics") or {}
        self.message_window = float(cfg.get("messageWindowSec", 60))
        self.command_window = float(cfg.get("commandWindowSec", 120))
        self.viewer_weight = float(cfg.get("viewerWeight", 0.4))
        self.cpm_weight = float(cfg.get("cpmWeight", 0.3))
        self.command_weight = float(cfg.get("commandWeight", 0.3))
        self.max_viewers = float(cfg.get("maxViewersForFull", 500))
        self.max_cpm = float(cfg.get("maxCpmForFull", 30))
        self.max_commands = float(cfg.get("maxCommandsForFull", 10))

        self._viewers: Dict[Platform, int] = {}
        self._messages: Deque[float] = deque()
        self._commands: Deque[float] = deque()

    def set_viewers(self, platform: Platform, count: int) -> None:
        self._viewers[platform] = max(0, int(count))

    def record_message(self, ts: Optional[float] = None) -> None:
        self._messages.append(ts or time.time())
        self._trim()

    def record_command(self, ts: Optional[float] = None) -> None:
        self._commands.append(ts or time.time())
        self._trim()

    def _trim(self) -> None:
        now = time.time()
        while self._messages and now - self._messages[0] > self.message_window:
            self._messages.popleft()
        while self._commands and now - self._commands[0] > self.command_window:
            self._commands.popleft()

    def snapshot(self) -> MetricsSnapshot:
        self._trim()
        total_viewers = sum(self._viewers.values())
        window = max(self.message_window, 1.0)
        cpm = (len(self._messages) / window) * 60.0
        cmd_rate = len(self._commands) / max(self.command_window / 60.0, 1e-6)

        def norm(val: float, max_v: float) -> float:
            if max_v <= 0:
                return 0.0
            return max(0.0, min(1.0, val / max_v))

        power = (
            self.viewer_weight * norm(total_viewers, self.max_viewers)
            + self.cpm_weight * norm(cpm, self.max_cpm)
            + self.command_weight * norm(cmd_rate, self.max_commands)
        )
        power_level = int(round(power * 15))

        return MetricsSnapshot(
            viewers=total_viewers,
            viewers_by_platform={p.value: c for p, c in self._viewers.items()},
            cpm=round(cpm, 2),
            command_rate=round(cmd_rate, 2),
            power_level=max(0, min(15, power_level)),
            ts=time.time(),
        )
