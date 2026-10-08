"""
What a game plugin is, and what Core hands it.

A game plugin can be:
  - a Python class in ``plugins/<id>/`` that subclasses ``BasePlugin`` (Minecraft, OpenTTD ...)
  - manifest-only (``"kind": "http"``): Core's ``HttpPlugin`` talks to the game's own bridge
    program over HTTP, no Python needed (Granvir)

Core calls start / stop / execute / on_metrics / health like it always did. Everything
below "optional hooks" is looked up with hasattr, so a plugin only writes what it needs.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urljoin

import httpx

from core.models import ChatReply, ExecuteRequest, MetricsSnapshot

log = logging.getLogger("core.plugin_api")


@dataclass
class PluginContext:
    """Core services handed to a plugin. Anything may be None in tests."""

    id: str
    folder: Path
    root: Path                                   # fridge-stream-core/
    data_dir: Path                               # data/plugins/<id>/ (created on first use)
    get_config: Callable[[], dict] = field(default=lambda: {})
    market: Any = None                           # core.market.MarketTape: quote, upsert, apply_return, try_signal
    store: Any = None                            # core.store.Store: points, get_or_create_user, pay_dividend
    bus: Any = None                              # core.event_bus.EventBus
    broadcast: Optional[Callable[[dict], Awaitable[None]]] = None   # WebSocket fan-out to overlays

    @property
    def config(self) -> dict:
        return self.get_config() or {}

    @property
    def section(self) -> dict:
        return dict(self.config.get(self.id) or {})

    def core_url(self) -> str:
        core = self.config.get("core") or {}
        return f"http://{core.get('host') or '127.0.0.1'}:{int(core.get('port') or 3850)}"

    async def reply(self, platform, text: str, to_user: str = "") -> None:
        """Say something as Core (chat reply + replies overlay)."""
        if self.bus is None or not text:
            return
        await self.bus.publish_reply(ChatReply(
            platform=platform, message=str(text), reply_to_user=to_user, target_platform=platform,
        ))

    async def alert(self, payload: dict) -> None:
        if self.bus is not None:
            await self.bus.publish_alert(payload)


class BasePlugin(abc.ABC):
    """Contract every game plugin implements. ``config`` is Core's whole live config."""

    name: str = "base"

    def __init__(self, config: dict, ctx: Optional[PluginContext] = None):
        self.ctx = ctx
        self.config = config
        self.enabled = True

    @property
    def config(self) -> dict:
        """Core's live config: dashboard saves replace it, and plugins see the new one at once."""
        ctx = getattr(self, "ctx", None)
        if ctx is not None:
            live = ctx.get_config()
            if live:
                return live
        return self._config

    @config.setter
    def config(self, value: dict) -> None:
        self._config = value

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def execute(self, req: ExecuteRequest) -> dict:
        """
        Run an approved chat command of this plugin's group.
        Return e.g. {"success": True} or {"success": False, "error": "..."};
        a "reply" key is said back in chat.
        """
        ...

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        """Optional: live metrics every 2 s (viewers, CPM, power_level 0-15)."""
        pass

    async def health(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Optional hooks (Core checks with hasattr / getattr)
    # ------------------------------------------------------------------
    # overlay_catalog() -> list[{name, url, notes}]       Sources + Integrations lists
    # status() -> dict                                    extra Status-row fields (detail, error ...)
    # async state_fragment() -> dict                      merged into the overlay "update" payload
    # market_status() -> list[str]                        lines under the plugin's Market sub-page
    # apply_config(config) -> None                        after a dashboard save (hot settings)
    # attach_market(tape) / attach_store(store)           older style; ctx.market / ctx.store also work
    #
    # Class-level (work while the game is off):
    # @classmethod routes(cls, router, get_running)       add FastAPI routes; get_running() -> instance | None
    # @staticmethod dividend_defaults(body, market_cfg)   {"symbol": ..., "rates": {...}} for /api/market/dividend


# Older name; outside code may still import it from games.base.
BaseGameIntegration = BasePlugin


class HttpPlugin(BasePlugin):
    """
    Manifest-only plugin: the game's bridge program speaks HTTP and Core relays to it.

    plugin.json:
      "kind": "http",
      "http": {
        "base_url_key": "bridge_url",              settings key holding the bridge address
        "health": "/stats",                        GET; 200 = healthy (and the body is kept as stats)
        "stats": "/stats",                         GET for fetch_stats (optional)
        "execute": "/command",                     POST {command, args, qty, user, platform} (optional)
        "metrics": "/api/metrics",                 POST {viewers, cpm, commands, powerLevel} (optional)
        "execute_error_hint": "..."                shown when the bridge can't be reached
      },
      "bridge_overlays": [{"name", "path", "notes"}]   pages the bridge serves itself
    """

    def __init__(self, config: dict, ctx: Optional[PluginContext] = None, manifest: Optional[dict] = None):
        super().__init__(config, ctx)
        self.manifest = manifest or {}
        self.name = str(self.manifest.get("id") or (ctx.id if ctx else "http"))
        self.http = dict(self.manifest.get("http") or {})
        section = (config or {}).get(self.name) or {}
        self.enabled = bool(section.get("enabled", False))
        key = str(self.http.get("base_url_key") or "bridge_url")
        default = str(((self.manifest.get("config_defaults") or {}).get(key)) or "http://127.0.0.1")
        self.bridge_url = str(section.get(key) or default).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self.last_stats: dict = {}

    def _url(self, which: str) -> str:
        path = str(self.http.get(which) or "")
        return f"{self.bridge_url}/{path.lstrip('/')}" if path else ""

    def overlay_catalog(self) -> list[dict]:
        return [
            {"name": str(p.get("name") or p.get("path")), "url": urljoin(self.bridge_url + "/", str(p.get("path") or "")),
             "notes": str(p.get("notes") or "")}
            for p in self.manifest.get("bridge_overlays") or []
            if isinstance(p, dict)
        ]

    async def start(self) -> None:
        if not self.enabled:
            return
        # X-Fridge-Core: Fridge bridges only accept writes that carry it
        self._client = httpx.AsyncClient(timeout=4.0, headers={"X-Fridge-Core": "1"})
        log.info("%s plugin ready (bridge=%s)", self.name, self.bridge_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(self, req: ExecuteRequest) -> dict:
        if not self.enabled or not self._client:
            return {"success": False, "error": f"{self.name} plugin not running"}
        url = self._url("execute")
        if not url:
            return {"success": False, "error": f"{self.name} takes no chat commands", "command": req.command_name}
        payload = {
            "command": req.command_name,
            "args": list(req.args or []),
            "qty": int(req.qty or 1),
            "user": getattr(req.user, "username", "") if req.user is not None else "",
            "platform": req.platform.value if req.platform else "",
        }
        try:
            r = await self._client.post(url, json=payload)
        except Exception as exc:
            hint = str(self.http.get("execute_error_hint") or f"{self.name} bridge not reachable")
            return {"success": False, "error": f"{hint}: {exc}", "command": req.command_name}
        if r.status_code != 200:
            return {"success": False, "error": f"bridge HTTP {r.status_code}", "command": req.command_name}
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return data if isinstance(data, dict) else {"success": True, "raw": data}

    async def on_metrics(self, snap: MetricsSnapshot) -> None:
        url = self._url("metrics")
        if not url or not self.enabled or not self._client:
            return
        try:
            await self._client.post(url, json={
                "viewers": snap.viewers,
                "cpm": snap.cpm,
                "commands": snap.command_rate,
                "powerLevel": snap.power_level,
            })
        except Exception:
            pass

    async def fetch_stats(self) -> dict:
        url = self._url("stats") or self._url("health")
        if not url or not self._client:
            return {}
        try:
            r = await self._client.get(url)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    self.last_stats = data
                    return data
        except Exception:
            pass
        return {}

    async def health(self) -> bool:
        url = self._url("health")
        if not self.enabled or not self._client or not url:
            return False
        try:
            r = await self._client.get(url)
        except Exception:
            return False
        if r.status_code != 200:
            return False
        if r.headers.get("content-type", "").startswith("application/json"):
            data = r.json()
            if isinstance(data, dict):
                self.last_stats = data
        return True
