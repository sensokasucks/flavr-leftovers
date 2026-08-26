"""Abstract game integration interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.models import ExecuteRequest, MetricsSnapshot


class BaseGameIntegration(ABC):
    id: str = "base"
    name: str = "Base"

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    @abstractmethod
    async def execute(self, req: ExecuteRequest) -> dict[str, Any]:
        ...

    async def on_metrics(self, snapshot: MetricsSnapshot) -> None:
        return None

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "id": self.id}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None
