"""
Factorio game integration.

Talks to the standalone Fridge Factorio Stats bridge (default :3847).
That process owns RCON + Wiretap + overlay files; Core only:
  - health-checks GET /stats
  - lists overlay URLs in Admin → Integrations
  - can later POST chat commands if the bridge grows an /api/execute

Enable with factorio.enabled=true and keep the Node bridge running.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin

import httpx

from core.models import ExecuteRequest, MetricsSnapshot
from games.base import BaseGameIntegration

log = logging.getLogger("games.factorio")

OVERLAY_PAGES = (
    ("Full stats overlay", "overlay.html", "Power, research, kills, deaths, evolution, alerts"),
    ("Power", "power.html", "Production / consumption"),
    ("Research", "research.html", "Current tech + progress"),
    ("Kills", "kills.html", "Biters down"),
    ("Deaths", "deaths.html", "Player deaths"),
    ("Evolution", "evolution.html", "Evolution factor"),
    ("Combat", "combat.html", "Kills + deaths"),
    ("Alerts", "alerts.html", "Factory alerts"),
)


class FactorioIntegration(BaseGameIntegration):
    name = "factorio"

    def __init__(self, config: dict):
        super().__init__(config)
        fx = config.get("factorio") or {}
        self.enabled = bool(fx.get("enabled", False))
        self.bridge_url = str(fx.get("bridge_url") or "http://127.0.0.1:3847").rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self.last_stats: dict = {}

    def overlay_catalog(self) -> list[dict]:
        base = self.bridge_url
        return [
            {"name": title, "url": urljoin(base + "/", path), "notes": notes}
            for title, path, notes in OVERLAY_PAGES
        ]

    async def start(self) -> None:
        if not self.enabled:
            log.info("Factorio integration disabled in config")
            return
        self._client = httpx.AsyncClient(timeout=4.0)
        log.info("Factorio integration ready (bridge=%s)", self.bridge_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(self, req: ExecuteRequest) -> dict:
        if not self.enabled:
            return {"success": False, "error": "factorio integration disabled"}
        return {
            "success": False,
            "error": "Factorio is stats/overlay only — chat commands are not sent into the factory yet",
            "command": req.command_name,
        }

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        # Overlay reads the Factorio bridge directly; nothing to push today.
        return

    async def fetch_stats(self) -> dict:
        if not self._client:
            return {}
        try:
            r = await self._client.get(f"{self.bridge_url}/stats")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    self.last_stats = data
                    return data
        except Exception:
            pass
        return {}

    async def health(self) -> bool:
        if not self.enabled or not self._client:
            return False
        try:
            r = await self._client.get(f"{self.bridge_url}/stats")
            if r.status_code == 200:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if isinstance(data, dict):
                    self.last_stats = data
                return True
            return False
        except Exception:
            return False
