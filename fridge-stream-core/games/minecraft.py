"""
Minecraft game integration.

Talks to the existing Fabric client-mod (stats) and server-mod
(command execution + Chat Dynamo) over HTTP. This keeps the Java
mods almost unchanged from the original design.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from core.models import ExecuteRequest, MetricsSnapshot
from games.base import BaseGameIntegration

log = logging.getLogger("games.minecraft")


class MinecraftIntegration(BaseGameIntegration):
    name = "minecraft"

    def __init__(self, config: dict):
        super().__init__(config)
        mc = config.get("minecraft", {})
        self.enabled = bool(mc.get("enabled", False))
        self.player = mc.get("player_name", "Player")
        self.client_url = mc.get("client_mod_url", "http://127.0.0.1:3852").rstrip("/")
        self.server_url = mc.get("server_mod_url", "http://127.0.0.1:3853").rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        if not self.enabled:
            log.info("Minecraft integration disabled in config")
            return
        self._client = httpx.AsyncClient(timeout=5.0)
        log.info(
            "Minecraft integration ready (client=%s server=%s player=%s)",
            self.client_url, self.server_url, self.player,
        )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(self, req: ExecuteRequest) -> dict:
        if not self.enabled or not self._client:
            return {"success": False, "error": "minecraft integration disabled"}

        # Special actions that talk to the client mod instead of running a command
        if req.special == "show_inventory":
            try:
                seconds = req.metadata.get("seconds", 12)
                await self._client.post(
                    f"{self.client_url}/api/show_inventory",
                    params={"seconds": seconds},
                )
                return {"success": True, "special": "show_inventory"}
            except Exception as e:
                log.warning("show_inventory failed: %s", e)
                return {"success": False, "error": str(e)}

        # Normal command → server mod
        try:
            r = await self._client.post(
                f"{self.server_url}/api/execute",
                json={
                    "command": req.template,
                    "player": self.player,
                    "source_user": req.user.username if req.user else "",
                    "platform": req.platform.value,
                    "original": req.original_message,
                },
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code < 400 and data.get("success", True)
            if not ok:
                log.warning("MC execute failed: %s %s", r.status_code, data)
            return {"success": ok, **data}
        except Exception as e:
            log.error("MC execute error: %s", e)
            return {"success": False, "error": str(e)}

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        if not self.enabled or not self._client:
            return
        try:
            await self._client.post(
                f"{self.server_url}/api/metrics",
                json={
                    "viewers": snap.viewers,
                    "cpm": snap.cpm,
                    "commands": snap.command_rate,
                    "powerLevel": snap.power_level,
                },
            )
        except Exception:
            # server mod may not be running yet – silent is fine
            pass

    async def fetch_client_stats(self) -> dict:
        """Used by the overlay / API layer."""
        if not self._client:
            return {}
        try:
            r = await self._client.get(f"{self.client_url}/api/stats")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    async def health(self) -> bool:
        if not self.enabled or not self._client:
            return False
        try:
            r = await self._client.get(f"{self.server_url}/api/health", timeout=2.0)
            return r.status_code < 500
        except Exception:
            return False
