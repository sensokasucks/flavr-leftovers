"""
FastAPI application – the public face of Stream Core.

Endpoints used by:
  - XSplit / OBS overlays
  - Game integrations (optional reverse registration)
  - Debugging / status
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

from api.admin_routes import create_admin_router

log = logging.getLogger("api.server")


class ConnectionManager:
    """Simple WebSocket fan-out for live overlay / debug clients."""

    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, data: dict) -> None:
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


def create_app(core_state: "CoreState") -> FastAPI:
    """
    core_state is a simple namespace object that main.py fills with
    the live MetricsAggregator, CommandRouter, game integrations, etc.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("API starting")
        yield
        log.info("API shutting down")

    app = FastAPI(
        title="Fridge Stream Core",
        version="0.11.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    manager = ConnectionManager()
    core_state.ws_manager = manager

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "adapters": list(core_state.adapters.keys()) if core_state.adapters else [],
            "games": list(core_state.games.keys()) if core_state.games else [],
        }

    @app.get("/api/metrics")
    async def get_metrics():
        if not core_state.metrics:
            return {"viewers": 0, "cpm": 0, "power_level": 0}
        return core_state.metrics.snapshot().to_dict()

    @app.get("/api/commands")
    async def list_commands():
        if not core_state.router:
            return []
        seen = set()
        out = []
        for name, cmd in core_state.router.commands.items():
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            out.append({
                "name": cmd.name,
                "aliases": cmd.aliases,
                "permission": cmd.permission.value,
                "description": cmd.description,
                "cost": cmd.cost,
                "examples": cmd.examples,
            })
        return out

    # ------------------------------------------------------------------
    # Minecraft / game-facing helpers (kept for compatibility)
    # ------------------------------------------------------------------

    async def build_state() -> dict:
        """Combined payload the overlay expects."""
        stats = {}
        inventory = None
        show_inv = False
        mc = (core_state.games or {}).get("minecraft")
        if mc and hasattr(mc, "fetch_client_stats"):
            stats = await mc.fetch_client_stats() or {}
            if stats.get("inventory"):
                inventory = stats["inventory"]
                show_inv = True

        metrics = {}
        if core_state.metrics:
            snap = core_state.metrics.snapshot()
            metrics = {
                "viewers": snap.viewers,
                "cpm": snap.cpm,
                "powerLevel": snap.power_level,
                "command_rate": snap.command_rate,
            }

        return {
            "type": "update",
            "stats": stats,
            "metrics": metrics,
            "showInventory": show_inv,
            "inventory": inventory,
        }

    # expose helper so main.py can push rich updates
    core_state.build_state = build_state

    @app.get("/api/stats")
    async def proxy_stats():
        """Proxy live player stats from the Minecraft client mod when available."""
        mc = (core_state.games or {}).get("minecraft")
        if mc and hasattr(mc, "fetch_client_stats"):
            return await mc.fetch_client_stats()
        return {}

    @app.get("/api/state")
    async def full_state():
        return await build_state()

    # ------------------------------------------------------------------
    # WebSocket for overlays / live dashboards
    # ------------------------------------------------------------------

    async def _ws_handler(ws: WebSocket):
        await manager.connect(ws)
        try:
            # Snapshot for stats overlay
            state = await build_state()
            await ws.send_json(state)
            # Recent chat for chat overlay (so reconnect isn't empty)
            history = getattr(core_state, "recent_chat", None) or []
            if history:
                await ws.send_json({"type": "chat_history", "data": list(history)})
            alerts = getattr(core_state, "recent_alerts", None) or []
            if alerts:
                await ws.send_json({"type": "alert_history", "data": list(alerts)})
            credits = getattr(core_state, "credits", None)
            if credits:
                await ws.send_json({"type": "credits_theme", "data": credits.theme})
                await ws.send_json({"type": "credits_play", "data": credits.public_play()})
                await ws.send_json({"type": "credits_roster", "data": credits.snapshot()})
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await _ws_handler(ws)

    # Root path so the existing overlay.js (ws://host/) keeps working
    @app.websocket("/")
    async def websocket_root(ws: WebSocket):
        await _ws_handler(ws)

    @app.get("/api/overlay/alerts-settings")
    async def overlay_alert_settings():
        """Public: overlay polls this so skin/CSS changes apply without a restart."""
        from core.alerts import read_alert_settings

        return read_alert_settings()

    def _credits():
        eng = getattr(core_state, "credits", None)
        if not eng:
            raise HTTPException(503, "Credits engine not ready")
        return eng

    @app.get("/api/credits/theme")
    async def credits_theme():
        return _credits().theme

    @app.get("/api/credits/roster")
    async def credits_roster():
        return _credits().snapshot()

    @app.get("/api/credits/play")
    async def credits_play():
        return _credits().public_play()

    @app.get("/api/credits/health")
    async def credits_health():
        eng = _credits()
        return {"ok": True, "enabled": eng.enabled, "count": len(eng.chatters)}

    # ------------------------------------------------------------------
    # Static overlay (if present)
    # ------------------------------------------------------------------

    # Admin API + dashboard
    app.include_router(create_admin_router(core_state))

    admin_dir = Path(__file__).resolve().parent.parent / "admin"
    if admin_dir.is_dir():
        app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")

    overlay_dir = Path(__file__).resolve().parent.parent / "overlay"
    if overlay_dir.is_dir():
        app.mount("/overlay", StaticFiles(directory=str(overlay_dir), html=True), name="overlay")

        @app.get("/", response_class=HTMLResponse)
        async def root():
            # Live-preview / STREAM_CORE_PREVIEW: land on the admin hub
            if os.environ.get("STREAM_CORE_PREVIEW", "").strip().lower() in (
                "1",
                "true",
                "yes",
            ):
                return RedirectResponse(url="/admin/", status_code=302)
            # Rewrite relative asset paths so HTML works from both / and /overlay/
            index = overlay_dir / "overlay.html"
            if index.exists():
                html = index.read_text(encoding="utf-8")
                html = html.replace('href="overlay.css"', 'href="/overlay/overlay.css"')
                html = html.replace('src="overlay.js"', 'src="/overlay/overlay.js"')
                html = html.replace("assets/", "/overlay/assets/")
                return html
            return "<h1>Fridge Stream Core</h1><p>No overlay.html found. Use /overlay/overlay.html</p>"

    return app


# Forward reference for type hints
class CoreState:
    """Mutable bag that main.py populates and the API reads."""
    def __init__(self):
        self.metrics = None
        self.router = None
        self.adapters: Dict[str, Any] = {}
        self.games: Dict[str, Any] = {}
        self.ws_manager: Optional[ConnectionManager] = None
        self.config: dict = {}
        self.build_state = None  # set by create_app
        self.recent_chat: list = []
        self.recent_alerts: list = []
        self.store = None
        self.fire_alert = None
        self.test_command = None
        self.test_metrics = None
        self.core = None
