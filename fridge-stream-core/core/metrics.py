"""
Live metrics aggregator.

Tracks chat rate (CPM), successful command rate, and viewer counts
across platforms. Produces the same 0–15 power_level that the
Minecraft Chat Dynamo already understands.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

from .models import MetricsSnapshot, Platform


class MetricsAggregator:
    """Rolling counters fed by main.py; ``snapshot()`` goes out on the EventBus every ~2 s.

    Settings come from the ``metrics:`` config block (camelCase keys, see the defaults below).
    Window lengths are in seconds; the weights should add up to 1.0.
    """
    def __init__(self, config: dict):
        m = config.get("metrics", {})
        self.message_window_sec = m.get("messageWindowSec", 60)
        self.command_window_sec = m.get("commandWindowSec", 120)
        self.viewer_weight = m.get("viewerWeight", 0.4)
        self.cpm_weight = m.get("cpmWeight", 0.3)
        self.command_weight = m.get("commandWeight", 0.3)
        self.max_viewers_for_full = m.get("maxViewersForFull", 500)
        self.max_cpm_for_full = m.get("maxCpmForFull", 30)
        self.max_commands_for_full = m.get("maxCommandsForFull", 10)

        self._message_ts: Deque[float] = deque()
        self._command_ts: Deque[float] = deque()
        self._viewers: Dict[str, int] = {}  # platform -> count

    def record_message(self) -> None:
        """Count one chat line now (feeds ``cpm``)."""
        self._message_ts.append(time.time())
        self._prune()

    def record_command(self) -> None:
        """Count one successful command now (feeds ``command_rate``)."""
        self._command_ts.append(time.time())
        self._prune()

    def set_viewers(self, platform: Platform | str, count: int) -> None:
        """Store the latest viewer count for one platform (negatives become 0)."""
        key = platform.value if isinstance(platform, Platform) else platform
        self._viewers[key] = max(0, int(count))

    def clear_viewers(self, platform: Platform | str) -> None:
        """Drop a platform's count (adapter stopped or switched channel)."""
        key = platform.value if isinstance(platform, Platform) else platform
        self._viewers.pop(key, None)

    def _prune(self) -> None:
        """Drop timestamps older than each window so the deques only hold recent events."""
        now = time.time()
        msg_cutoff = now - self.message_window_sec
        while self._message_ts and self._message_ts[0] < msg_cutoff:
            self._message_ts.popleft()

        cmd_cutoff = now - self.command_window_sec
        while self._command_ts and self._command_ts[0] < cmd_cutoff:
            self._command_ts.popleft()

    @property
    def total_viewers(self) -> int:
        return sum(self._viewers.values())

    @property
    def cpm(self) -> float:
        """Chat messages per minute over the message window."""
        self._prune()
        # messages in the window, scaled to per-minute
        return len(self._message_ts) * (60.0 / max(1, self.message_window_sec))

    @property
    def command_rate(self) -> float:
        """Commands within the command window (a count, not per minute)."""
        self._prune()
        return float(len(self._command_ts))

    def compute_power_level(self) -> int:
        """0–15 scale, identical math to the original Minecraft bridge."""
        v_norm = min(1.0, self.total_viewers / max(1, self.max_viewers_for_full))
        c_norm = min(1.0, self.cpm / max(1, self.max_cpm_for_full))
        cmd_norm = min(1.0, self.command_rate / max(1, self.max_commands_for_full))

        score = (
            v_norm * self.viewer_weight
            + c_norm * self.cpm_weight
            + cmd_norm * self.command_weight
        )
        return int(round(min(15, max(0, score * 15))))

    def snapshot(self) -> MetricsSnapshot:
        """Current numbers as a ``MetricsSnapshot`` (cpm rounded to 1 decimal)."""
        return MetricsSnapshot(
            viewers=self.total_viewers,
            viewers_by_platform=dict(self._viewers),
            cpm=round(self.cpm, 1),
            command_rate=self.command_rate,
            power_level=self.compute_power_level(),
            timestamp=time.time(),
        )
