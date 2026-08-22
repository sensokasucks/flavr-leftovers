"""
Contract that every game integration implements.

A game integration can be:
  - Minecraft (HTTP to Fabric mods)
  - Factorio (RCON / Wiretap)
  - or anything else that consumes ExecuteRequest + MetricsSnapshot
"""

from __future__ import annotations

import abc
from typing import Any

from core.models import ExecuteRequest, MetricsSnapshot


class BaseGameIntegration(abc.ABC):
    name: str = "game"

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def execute(self, req: ExecuteRequest) -> dict:
        """Run an approved command. Return {success: bool, ...}."""
        ...

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        """Optional: react to live metrics (e.g. Chat Dynamo power level)."""
        return None
