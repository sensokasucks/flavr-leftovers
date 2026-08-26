"""
Contract that every game integration implements.

A game integration can be:
  - an in-process Python class (simple games / tools)
  - a remote process that Core talks to over HTTP (Minecraft mods, Factorio, etc.)

For remote games we already have a working pattern from the old bridge:
  Core POSTs to the game's /api/execute and /api/metrics endpoints.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

from core.models import ExecuteRequest, MetricsSnapshot

log = logging.getLogger("games.base")


class BaseGameIntegration(abc.ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.enabled = True

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def execute(self, req: ExecuteRequest) -> dict:
        """
        Run the approved command/action.
        Return a small result dict, e.g. {"success": True} or {"success": False, "error": "..."}.
        """
        ...

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        """Optional: receive live metrics (viewers, CPM, power_level)."""
        pass

    async def health(self) -> bool:
        return True
