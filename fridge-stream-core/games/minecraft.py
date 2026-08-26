"""Minecraft Fabric mod integration (client :3852, server :3853)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.models import ExecuteRequest, MetricsSnapshot
from games.base import BaseGameIntegration

log = logging.getLogger("fridge.minecraft")


class MinecraftIntegration(BaseGameIntegration):
    id = "minecraft"
    name = "Minecraft"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.client_url = (config or {}).get("client_mod_url", "http://127.0.0.1:3852").rstrip("/")
        self.server_url = (config or {}).get("server_mod_url", "http://127.0.0.1:3853").rstrip("/")
        self.player_name = (config or {}).get("player_name", "")
        self._client = httpx.AsyncClient(timeout=5.0)

    @property
    def enabled(self) -> bool:
        # Missing key => off (opt-in)
        return bool(self.config.get("enabled", False))

    async def execute(self, req: ExecuteRequest) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "minecraft disabled"}
        payload = {
            "command": req.command,
            "args": req.args,
            "quantity": req.quantity,
            "seconds": req.seconds,
            "template": req.template,
            "user": req.user.username if req.user else "",
            "meta": req.meta,
        }
        try:
            r = await self._client.post(f"{self.server_url}/execute", json=payload)
            return {"ok": r.is_success, "status": r.status_code, "body": r.text[:500]}
        except Exception as exc:
            log.warning("execute failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def on_metrics(self, snapshot: MetricsSnapshot) -> None:
        if not self.enabled:
            return
        body = {
            "viewers": snapshot.viewers,
            "cpm": snapshot.cpm,
            "powerLevel": snapshot.power_level,
            "commandRate": snapshot.command_rate,
        }
        try:
            await self._client.post(f"{self.server_url}/metrics", json=body)
        except Exception as exc:
            log.debug("metrics push failed: %s", exc)

    async def health(self) -> dict[str, Any]:
        result = {"id": self.id, "enabled": self.enabled, "client": False, "server": False}
        if not self.enabled:
            return result
        try:
            r = await self._client.get(f"{self.client_url}/health")
            result["client"] = r.is_success
        except Exception:
            pass
        try:
            r = await self._client.get(f"{self.server_url}/health")
            result["server"] = r.is_success
        except Exception:
            pass
        result["ok"] = result["client"] or result["server"]
        return result

    async def stop(self) -> None:
        await self._client.aclose()
