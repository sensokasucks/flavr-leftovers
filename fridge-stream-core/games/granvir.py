"""
Granvir game integration.

Talks to Fridge Granvir Stats (BepInEx plugin or the mock bridge).
Default bridge: http://127.0.0.1:3855

Core only:
  - health-checks GET /stats
  - lists overlay URLs in Admin → Integrations
  - POSTs /command later when the plugin exposes host-only actions

Enable with granvir.enabled=true and run the plugin (or mock/mock_server.py).
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin

import httpx

from core.models import ExecuteRequest, MetricsSnapshot
from games.base import BaseGameIntegration

log = logging.getLogger("games.granvir")

OVERLAY_PAGES = (
    ("Full stats overlay", "overlay.html", "Health, heat, campaign, squad"),
    ("Health", "health.html", "Pilot / mech durability"),
    ("Heat", "heat.html", "Generator heat"),
    ("Campaign", "campaign.html", "Region, hours, credits, threat"),
    ("Squad", "squad.html", "Co-op pilots"),
)


class GranvirIntegration(BaseGameIntegration):
    name = "granvir"

    def __init__(self, config: dict):
        super().__init__(config)
        gv = config.get("granvir") or {}
        self.enabled = bool(gv.get("enabled", False))
        self.bridge_url = str(gv.get("bridge_url") or "http://127.0.0.1:3855").rstrip("/")
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
            log.info("Granvir integration disabled in config")
            return
        self._client = httpx.AsyncClient(timeout=4.0)
        log.info("Granvir integration ready (bridge=%s)", self.bridge_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(self, req: ExecuteRequest) -> dict:
        if not self.enabled:
            return {"success": False, "error": "granvir integration disabled"}
        if not self._client:
            return {"success": False, "error": "granvir client not started"}
        user = ""
        if req.user is not None:
            user = getattr(req.user, "username", "") or ""
        payload = {
            "command": req.command_name,
            "args": list(req.args or []),
            "qty": int(req.qty or 1),
            "user": user,
        }
        try:
            r = await self._client.post(f"{self.bridge_url}/command", json=payload)
            if r.status_code == 200:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if isinstance(data, dict):
                    return data
                return {"success": True, "raw": data}
            return {
                "success": False,
                "error": f"bridge HTTP {r.status_code}",
                "command": req.command_name,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": f"Granvir commands are host-only and need the BepInEx plugin: {exc}",
                "command": req.command_name,
            }

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
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
