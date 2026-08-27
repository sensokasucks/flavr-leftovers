"""HTTP + WebSocket surface for the control desk and XSplit overlay."""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from core.models import ChatEvent, ChatUser, Platform
from core.config import DEFAULTS, save_config as write_yaml_config

log = logging.getLogger("api.server")


class ConnectionManager:
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


class AppState:
    """Filled by main.py."""

    def __init__(self):
        self.config: dict = {}
        self.roster = None
        self.ws: Optional[ConnectionManager] = None
        self.root: Optional[Path] = None
        self.theme: dict = {}
        self.play: dict = {
            "playing": True,
            "mode": "loop",
            "freeze": False,
            "frozen_roster": None,
            "generation": 0,
        }
        self.adapters: dict = {}
        self.bus = None
        self.cast = None


def _theme_path(state: AppState) -> Path:
    return state.root / "data" / "theme.json"


def load_theme(state: AppState) -> dict:
    theme = dict(state.config.get("credits") or {})
    path = _theme_path(state)
    if path.exists():
        try:
            override = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(override, dict):
                theme.update(override)
        except Exception:
            log.exception("theme override unreadable")
    state.theme = theme
    return theme


def save_theme(state: AppState) -> None:
    path = _theme_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.theme, indent=2), encoding="utf-8")


def roster_payload(state: AppState) -> dict:
    sort = (state.theme or {}).get("sort") or "first_seen"
    if state.play.get("freeze") and state.play.get("frozen_roster"):
        snap = state.play["frozen_roster"]
    else:
        snap = state.roster.snapshot(sort=sort)
        if getattr(state, "cast", None):
            style = state.cast.get_style()
            snap["style"] = style.get("style") or "names"
            snap["style_id"] = state.cast.style_id
            snap = state.cast.decorate(snap, state.roster.started_at)
    return snap


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="Fridge Chat Credits", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    manager = ConnectionManager()
    state.ws = manager

    overlay_dir = Path(__file__).resolve().parent.parent / "overlay"

    @app.middleware("http")
    async def no_cache_overlay(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith((".html", ".js", ".css")) or path in ("/", "/credits"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "adapters": list(state.adapters.keys()),
            "count": len(state.roster.chatters) if state.roster else 0,
        }

    def _public_play():
        return {k: v for k, v in state.play.items() if k != "frozen_roster"}

    @app.get("/api/config")
    async def get_config():
        return {
            "config": state.config,
            "defaults": DEFAULTS,
            "note": "Saving platforms / ingest requires a restart of Chat Credits.",
        }

    @app.put("/api/config")
    async def put_config(body: dict[str, Any]):
        incoming = body.get("config") if isinstance(body.get("config"), dict) else body
        if not isinstance(incoming, dict) or not incoming:
            return JSONResponse({"ok": False, "error": "config object required"}, status_code=400)
        # Keep current look if the editor didn't send credits
        if "credits" not in incoming and state.theme:
            incoming = dict(incoming)
            incoming["credits"] = dict(state.theme)
        path = write_yaml_config(state.root, incoming)
        state.config = incoming
        apply = getattr(state, "apply_config", None)
        if callable(apply):
            apply(incoming)
        return {
            "ok": True,
            "path": str(path),
            "message": "Saved. Restart Chat Credits if you changed Twitch / Kick / YouTube / ingest.",
        }

    @app.get("/api/roster")
    async def get_roster():
        return roster_payload(state)

    @app.get("/api/roster.csv")
    async def roster_csv():
        snap = roster_payload(state)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["platform", "username", "display_name", "messages", "first_seen", "mod"])
        for c in snap.get("chatters") or []:
            writer.writerow([
                c.get("platform"),
                c.get("username"),
                c.get("display_name"),
                c.get("messages"),
                c.get("first_seen"),
                int(bool(c.get("is_mod"))),
            ])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=chatters.csv"},
        )

    @app.post("/api/session/reset")
    async def reset_session():
        state.roster.reset()
        state.play["frozen_roster"] = None
        state.play["freeze"] = False
        snap = roster_payload(state)
        await manager.broadcast({"type": "roster", "data": snap})
        await manager.broadcast({"type": "play", "data": state.play})
        return {"ok": True, "count": 0}

    @app.get("/api/theme")
    async def get_theme():
        return state.theme

    @app.put("/api/theme")
    async def put_theme(body: dict[str, Any]):
        persist = bool(body.pop("persist", True))
        body.pop("persist", None)
        state.theme.update(body)
        if persist:
            save_theme(state)
        await manager.broadcast({"type": "theme", "data": state.theme})
        return state.theme

    @app.get("/api/play")
    async def get_play():
        out = dict(state.play)
        out.pop("frozen_roster", None)
        return out

    @app.post("/api/play")
    async def set_play(body: dict[str, Any]):
        if "playing" in body:
            state.play["playing"] = bool(body["playing"])
        if "mode" in body and body["mode"] in ("loop", "once", "hold"):
            state.play["mode"] = body["mode"]
            state.theme["mode"] = body["mode"]
        if "freeze" in body:
            freeze = bool(body["freeze"])
            state.play["freeze"] = freeze
            if freeze:
                state.play["frozen_roster"] = roster_payload(state)
            else:
                state.play["frozen_roster"] = None
        if body.get("restart"):
            state.play["generation"] = int(state.play.get("generation") or 0) + 1
        public = {k: v for k, v in state.play.items() if k != "frozen_roster"}
        await manager.broadcast({"type": "play", "data": public})
        await manager.broadcast({"type": "roster", "data": roster_payload(state)})
        return public

    @app.post("/api/seed")
    async def seed(body: dict[str, Any]):
        """Add a test chatter without a live platform."""
        if not state.bus:
            return JSONResponse({"ok": False, "error": "bus not ready"}, status_code=503)
        name = (body.get("username") or body.get("display_name") or "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "username required"}, status_code=400)
        plat_raw = (body.get("platform") or "manual").lower()
        try:
            plat = Platform(plat_raw)
        except ValueError:
            plat = Platform.MANUAL
        user = ChatUser(
            platform=plat,
            id=name,
            username=name,
            display_name=body.get("display_name") or name,
            is_mod=bool(body.get("is_mod")),
        )
        await state.bus.publish_chat(ChatEvent(
            platform=plat,
            user=user,
            message=body.get("message") or "(seed)",
        ))
        return {"ok": True, "count": len(state.roster.chatters)}

    @app.get("/api/cast")
    async def get_cast():
        board = state.cast
        if not board:
            return {"styles": [], "style_id": "names", "overrides": []}
        return {
            "styles": board.list_styles(),
            "style_id": board.style_id,
            "style": board.get_style(),
            "overrides": list(board.overrides.values()),
            "job_max": 50,
        }

    @app.put("/api/cast/style")
    async def put_cast_style(body: dict[str, Any]):
        board = state.cast
        if not board:
            return JSONResponse({"ok": False}, status_code=503)
        sid = board.set_style(str(body.get("style_id") or body.get("id") or "names"))
        state.theme["style_id"] = sid
        state.theme["style"] = board.get_style().get("style") or "names"
        save_theme(state)
        snap = roster_payload(state)
        await manager.broadcast({"type": "theme", "data": state.theme})
        await manager.broadcast({"type": "roster", "data": snap})
        return {"ok": True, "style_id": sid, "style": board.get_style()}

    @app.put("/api/cast/file")
    async def put_cast_file(body: dict[str, Any]):
        board = state.cast
        if not board:
            return JSONResponse({"ok": False}, status_code=503)
        try:
            saved = board.save_style(body)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return {"ok": True, "style": saved, "styles": board.list_styles()}

    @app.post("/api/cast/pin")
    async def pin_cast(body: dict[str, Any]):
        board = state.cast
        if not board:
            return JSONResponse({"ok": False}, status_code=503)
        name = (body.get("username") or "").strip().lstrip("@")
        plat = (body.get("platform") or "twitch").lower()
        job = body.get("job") or ""
        if (body.get("clear") or str(job).lower() == "clear"):
            board.unpin(plat, name)
        else:
            try:
                board.pin(plat, name, job, set_by="desk")
            except ValueError as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        snap = roster_payload(state)
        await manager.broadcast({"type": "roster", "data": snap})
        return {"ok": True, "overrides": list(board.overrides.values())}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await manager.connect(ws)
        try:
            await ws.send_json({"type": "theme", "data": state.theme})
            public = {k: v for k, v in state.play.items() if k != "frozen_roster"}
            await ws.send_json({"type": "play", "data": public})
            await ws.send_json({"type": "roster", "data": roster_payload(state)})
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    # Canonical overlay paths (same contract as Stream Core's built-in credits)
    @app.get("/api/credits/theme")
    async def credits_theme():
        return state.theme

    @app.put("/api/credits/theme")
    async def credits_put_theme(body: dict[str, Any]):
        return await put_theme(body)

    @app.get("/api/credits/roster")
    async def credits_roster():
        return roster_payload(state)

    @app.get("/api/credits/play")
    async def credits_play():
        return _public_play()

    @app.post("/api/credits/play")
    async def credits_set_play(body: dict[str, Any]):
        return await set_play(body)

    @app.post("/api/credits/session/reset")
    async def credits_reset():
        return await reset_session()

    @app.post("/api/credits/seed")
    async def credits_seed(body: dict[str, Any]):
        return await seed(body)

    if overlay_dir.is_dir():
        app.mount("/overlay", StaticFiles(directory=str(overlay_dir), html=True), name="overlay")

        @app.get("/", response_class=HTMLResponse)
        async def root():
            path = overlay_dir / "control.html"
            if path.exists():
                return path.read_text(encoding="utf-8")
            return "<h1>Fridge Chat Credits</h1>"

        @app.get("/credits", response_class=HTMLResponse)
        async def credits_alias():
            path = overlay_dir / "credits.html"
            return path.read_text(encoding="utf-8") if path.exists() else "missing"

    return app
