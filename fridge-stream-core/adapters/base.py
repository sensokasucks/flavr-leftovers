"""Abstract chat platform adapter."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, Optional

from core.models import ChatEvent, Platform
from core.metrics import MetricsAggregator

log = logging.getLogger("fridge.adapter")

EmitFn = Callable[[ChatEvent], Awaitable[None]]


class BaseAdapter(ABC):
    platform: Platform = Platform.SYSTEM

    def __init__(
        self,
        config: dict | None = None,
        *,
        metrics: Optional[MetricsAggregator] = None,
        emit: Optional[EmitFn] = None,
    ) -> None:
        self.config = config or {}
        self.metrics = metrics
        self._emit_fn = emit
        self._task: asyncio.Task | None = None
        self._stopping = False

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    async def _emit(self, event: ChatEvent) -> None:
        if self._emit_fn:
            await self._emit_fn(event)

    @abstractmethod
    async def run(self) -> None:
        """Long-running listen loop."""

    async def start(self) -> None:
        if not self.enabled:
            log.info("%s adapter disabled", self.platform.value)
            return
        self._stopping = False
        self._task = asyncio.create_task(self.run(), name=f"adapter-{self.platform.value}")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
