"""
FastAPI application – the public face of Stream Core.

Endpoints used by:
  - XSplit / OBS overlays
  - Game integrations (optional reverse registration)
  - Debugging / status
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

from api.admin_routes import create_admin_router
from core.local_guard import LOOPBACK_ORIGIN_REGEX, LocalGuard, LocalGuardMiddleware

log = logging.getLogger("api.server")


class ConnectionManager:
    """Simple WebSocket fan-out for live overlay / debug clients.

    The end-credits roster (every unique chatter of the session) grows to megabytes on a
    long stream, so it only goes to clients that ask for it by connecting to
    ``/ws?credits=1`` (the credits overlay and the dashboard's Credits tab), and at most
    once every ``ROSTER_MIN_GAP_SEC``. Everyone else (chat overlay, Stream Rooms) never
    gets it: a 2 MB message per new chatter filled Stream Rooms' receive buffer and made
    it drop the connection over and over.
    """

    ROSTER_MIN_GAP_SEC = 3.0
    # Each client gets its own send queue and sender task, so one slow or stuck client (a
    # hidden OBS source, Stream Rooms loading a room, a background laptop tab) never holds up
    # chat for the others. A client that falls this many messages behind, or whose single
    # send takes longer than SEND_TIMEOUT_SEC, is disconnected; overlays reconnect by
    # themselves and catch up from chat_history.
    SEND_QUEUE_MAX = 1000
    SEND_TIMEOUT_SEC = 15.0
    # A full queue waits this long for its sender to make room before the client counts as stuck
    # (a burst sent with no pause: on Python 3.10 one send takes a few loop turns).
    SEND_ROOM_WAIT_SEC = 0.25

    def __init__(self):
        self.active: Set[WebSocket] = set()
        self.credits_clients: Set[WebSocket] = set()
        self._roster_fn = None              # callable -> current roster snapshot
        self._roster_task: Optional[asyncio.Task] = None
        self._roster_sent_at = 0.0
        self._senders: Dict[WebSocket, "_ClientSender"] = {}
        self.dropped_slow = 0               # clients cut off for falling behind (Status / tests)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)
        self._senders[ws] = _ClientSender(self, ws)
        if _wants_credits(ws):
            self.credits_clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)
        self.credits_clients.discard(ws)
        sender = self._senders.pop(ws, None)
        if sender is not None:
            sender.stop()

    def drop_slow(self, ws: WebSocket, why: str) -> None:
        """Cut off a client that can't keep up; it reconnects and catches up on its own."""
        if ws not in self.active:
            return
        self.dropped_slow += 1
        log.warning("Disconnected a slow overlay / client (%s); it will reconnect", why)
        self.disconnect(ws)

        async def _close():
            try:
                await asyncio.wait_for(ws.close(code=1013), timeout=2.0)
            except Exception:
                pass

        try:
            asyncio.get_running_loop().create_task(_close())
        except RuntimeError:
            pass

    async def flush(self) -> None:
        """Wait until every queued message went out (tests, shutdown)."""
        for sender in list(self._senders.values()):
            await sender.queue.join()

    async def broadcast(self, data: dict) -> None:
        if isinstance(data, dict) and data.get("type") == "credits_roster":
            await self._send_all(self.credits_clients, data)
            return
        await self._send_all(self.active, data)

    def push_roster(self, snapshot_fn) -> None:
        """The roster changed: send it to the credits clients soon (coalesced, throttled).
        Nothing is built while no credits client is connected."""
        self._roster_fn = snapshot_fn
        if not self.credits_clients:
            return
        if self._roster_task is not None and not self._roster_task.done():
            return              # a send is already scheduled; it will pick up the latest roster
        try:
            self._roster_task = asyncio.get_running_loop().create_task(self._roster_later(), name="credits-roster-push")
        except RuntimeError:
            pass                # no event loop (tests calling from sync code)

    async def _roster_later(self) -> None:
        wait = self.ROSTER_MIN_GAP_SEC - (time.monotonic() - self._roster_sent_at)
        if wait > 0:
            await asyncio.sleep(wait)
        fn = self._roster_fn
        if fn is None or not self.credits_clients:
            return
        self._roster_sent_at = time.monotonic()
        await self._send_all(self.credits_clients, {"type": "credits_roster", "data": fn()})

    async def _send_all(self, clients: Set[WebSocket], data: dict) -> None:
        """Queue one message for each client; returns at once (each client's task sends it)."""
        if not clients:
            return
        text = json.dumps(data)         # serialise once, not once per client
        for ws in list(clients):
            sender = self._senders.get(ws)
            if sender is None:
                continue
            if not sender.offer(text):
                # a burst with no pause in between: give the client's sender a moment to make
                # room, then cut it off if it is still that far behind (a stuck client costs
                # this wait once, then it's gone)
                try:
                    await asyncio.wait_for(sender.queue.put(text), timeout=self.SEND_ROOM_WAIT_SEC)
                except asyncio.TimeoutError:
                    self.drop_slow(ws, f"{self.SEND_QUEUE_MAX} messages behind")


class _ClientSender:
    """One WebSocket client's outgoing queue, sent in order by its own task."""

    def __init__(self, manager: ConnectionManager, ws: WebSocket):
        self.manager = manager
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=manager.SEND_QUEUE_MAX)
        self.task = asyncio.get_running_loop().create_task(self._run(), name="ws-send")

    def offer(self, text: str) -> bool:
        try:
            self.queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            return False

    def stop(self) -> None:
        if not self.task.done():
            self.task.cancel()
        # let flush() waiters go
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except Exception:
                break

    async def _run(self) -> None:
        while True:
            text = await self.queue.get()
            try:
                await asyncio.wait_for(self.ws.send_text(text), timeout=self.manager.SEND_TIMEOUT_SEC)
            except asyncio.CancelledError:
                self.queue.task_done()
                raise
            except asyncio.TimeoutError:
                self.queue.task_done()
                self.manager.drop_slow(self.ws, "a send took too long")
                return
            except Exception:
                self.queue.task_done()
                self.manager.disconnect(self.ws)   # gone
                return
            self.queue.task_done()


def _wants_credits(ws: WebSocket) -> bool:
    try:
        return str(ws.query_params.get("credits", "")).lower() in ("1", "true", "yes")
    except Exception:
        return False


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

    @app.middleware("http")
    async def no_cache_pages(request, call_next):
        # OBS / browser sources cache overlay files hard; an update should show
        # up on the next reload without clearing the browser-source cache.
        response = await call_next(request)
        path = request.url.path
        if path.startswith(("/overlay/", "/admin")) and (
            path.endswith((".html", ".js", ".css", "/")) or path == "/admin"
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    # CORS only for our own loopback pages (was "*": any site could drive the API).
    extra_origins = list(((core_state.config or {}).get("core") or {}).get("allowed_origins") or [])
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOOPBACK_ORIGIN_REGEX,
        allow_origins=extra_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Outermost: refuse foreign Origin / Host (CSRF + DNS rebinding).
    app.add_middleware(LocalGuardMiddleware, guard=LocalGuard(core_state.config or {}))

    manager = ConnectionManager()
    core_state.ws_manager = manager

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health():
        adapters = core_state.adapters or {}
        return {
            "ok": True,
            "adapters": list(adapters.keys()),
            # for the overlays' "why is this empty" line in a normal browser tab
            "connected": [n for n, a in adapters.items() if getattr(a, "connected", False)],
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
    # Overlay "update" payload (metrics overlay + game plugins' extras)
    # ------------------------------------------------------------------

    async def build_state() -> dict:
        """Combined payload the overlays expect. Game plugins add their keys
        (Minecraft: stats / inventory, OpenTTD: openttd) through state_fragment()."""
        metrics = {}
        if core_state.metrics:
            snap = core_state.metrics.snapshot()
            metrics = {
                "viewers": snap.viewers,
                "cpm": snap.cpm,
                "powerLevel": snap.power_level,
                "command_rate": snap.command_rate,
            }

        ov = (getattr(core_state, "config", None) or {}).get("overlay") or {}
        modules = dict((ov.get("modules") or {}))
        payload = {
            "type": "update",
            "stats": {},
            "metrics": metrics,
            "showInventory": False,
            "inventory": None,
            "overlay": {
                "modules": modules,
                "show_inventory_seconds": ov.get("show_inventory_seconds", 12),
            },
        }
        plugins = getattr(core_state, "plugins", None)
        if plugins is not None:
            extra = await plugins.state_fragments()
            extra.pop("type", None)
            extra.pop("metrics", None)
            extra.pop("overlay", None)
            payload.update(extra)
        return payload

    # expose helper so main.py can push rich updates
    core_state.build_state = build_state

    @app.get("/api/state")
    async def full_state():
        return await build_state()

    # Game plugins' own routes (/api/stats for Minecraft, /api/openttd/state ...): registered for
    # every installed plugin, so they answer "not running" while the game is off.
    plugins = getattr(core_state, "plugins", None)
    if plugins is not None:
        plugin_router = APIRouter()
        plugins.register_routes(
            plugin_router,
            lambda pid: (lambda: (core_state.games or {}).get(pid)),
        )
        app.include_router(plugin_router)

    def _market():
        tape = getattr(core_state, "market", None)
        if tape is None:
            raise HTTPException(503, "Market tape not ready")
        return tape

    @app.get("/api/market/state")
    async def market_state(book: str = "", symbols: str = ""):
        tape = _market()
        want = [s.strip() for s in (symbols or "").split(",") if s.strip()]
        return tape.snapshot(book=book or None, symbols=want or None)

    @app.get("/api/overlay/replies")
    async def overlay_replies():
        ov = (getattr(core_state, "config", None) or {}).get("overlay") or {}
        return {"enabled": bool(ov.get("replies_enabled"))}

    @app.get("/api/market/history")
    async def market_history(symbol: str = "FRG", points: int = 120):
        tape = _market()
        return tape.history(symbol, points=max(8, min(int(points or 120), 2000)))

    @app.post("/api/market/signal")
    async def market_signal(payload: dict):
        """Preview ingest: death / named signals honor optional cooldowns."""
        tape = _market()
        cfg = (getattr(core_state, "config", None) or {}).get("market") or {}
        name = str((payload or {}).get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name required")
        symbol = (payload or {}).get("symbol")
        book = (payload or {}).get("book") or (payload or {}).get("game")
        cooldown = payload.get("cooldown_sec")
        if cooldown is None:
            if name == "player_death":
                cooldown = cfg.get("death_cooldown_sec", 20)
            else:
                cooldown = cfg.get("signal_cooldown_sec", 15)
        scope = str(payload.get("scope") or cfg.get("signal_cooldown_scope") or "symbol")
        gate = tape.try_signal(
            name=name,
            symbol=symbol,
            cooldown_sec=cooldown,
            book=book,
            scope=scope,
        )
        if not gate.get("ok"):
            return {**gate, "applied": False}
        frac = payload.get("pct")
        if frac is None and name == "player_death":
            frac = float(cfg.get("death_return", -0.08) or -0.08)
        elif frac is not None:
            frac = float(frac) / 100.0 if abs(float(frac)) > 1 else float(frac)
        applied = None
        if frac is not None and symbol:
            applied = tape.apply_return(str(symbol), float(frac), reason=name)
        return {**gate, "applied": bool(applied), "instrument": applied, "last_event": tape.last_event}

    @app.post("/api/market/dividend")
    async def market_dividend(payload: dict):
        """
        Vault flush from a game bridge.
        Body: { game, symbol, work, unit, reason?, points? }
        work*points_per_unit becomes a points pool paid to holders of symbol.
        Also bumps the ticker so the tape reacts even with zero holders.
        """
        tape = _market()
        cfg = (getattr(core_state, "config", None) or {}).get("market") or {}
        body = payload or {}
        symbol = str(body.get("symbol") or "").upper().strip()
        # Older Factorio bridges send no game name; the plugin that owns the book fills the gaps
        game = str(body.get("game") or body.get("book") or "factorio").strip()
        if game.startswith("game:"):
            game = game[5:]
        plugins = getattr(core_state, "plugins", None)
        hints = plugins.dividend_defaults(game, body, cfg) if plugins is not None else {}
        if not symbol:
            symbol = str(hints.get("symbol") or "").upper().strip()
            if not symbol:
                raise HTTPException(400, "symbol required")
        work = float(body.get("work") or 0)
        unit = str(body.get("unit") or "mj").lower()
        reason = str(body.get("reason") or "vault")
        rates = (cfg.get("points_per_unit") or {})
        if isinstance(hints.get("rates"), dict):
            rates = hints["rates"]
        per = body.get("points")
        if per is None:
            default_rate = 0.02 if unit in ("mj", "joule", "j") else 1.0
            per = work * float(rates.get(unit, rates.get("mj" if unit == "joule" else unit, default_rate)))
        points = int(max(0, round(float(per))))
        hourly_cap = int(cfg.get("hourly_cap_points") or 500)
        points = min(points, hourly_cap)

        store = getattr(core_state, "store", None)
        paid = {"holders": 0, "paid": [], "burned": points, "total": points}
        if store and hasattr(store, "pay_dividend") and points > 0:
            paid = await store.pay_dividend(symbol, points, f"{reason}:{unit}")

        bump = float(cfg.get("dividend_price_bump", 0.01) or 0)
        applied = tape.apply_return(symbol, bump, reason=f"dividend:{reason}") if bump else None
        event = {
            "ts": time.time(),
            "symbol": symbol,
            "game": game,
            "unit": unit,
            "work": work,
            "points": points,
            "holders": paid.get("holders", 0),
            "burned": paid.get("burned", points),
            "reason": reason,
        }
        tape.last_dividend = event
        tape.last_event = {
            "ts": event["ts"],
            "symbol": symbol,
            "reason": f"dividend {points} pts",
            "pct": round(bump * 100.0, 2),
        }
        return {"ok": True, "dividend": event, "instrument": applied, "payout": paid}

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
            replies = getattr(core_state, "recent_replies", None) or []
            if replies:
                await ws.send_json({"type": "reply_history", "data": list(replies)})
            games = getattr(core_state, "chat_games", None)
            if games is not None and games.boards:
                await ws.send_json({"type": "board_history", "data": games.board_state()})
            credits = getattr(core_state, "credits", None)
            if credits:
                await ws.send_json({"type": "credits_theme", "data": credits.theme})
                await ws.send_json({"type": "credits_play", "data": credits.public_play()})
                if ws in manager.credits_clients:
                    await ws.send_json({"type": "credits_roster", "data": credits.snapshot()})
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_json({"type": "pong"})
                    continue
                # JSON messages from a game client (Stream Rooms): hello,
                # room_state, reaction_result, say, overlay. Anything else
                # is ignored so old overlays keep working.
                if data[:1] != "{":
                    continue
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "avatars_hide_import":
                    # Stream Rooms' "hide pictures for these names" list: merged into Core's
                    importer = getattr(core_state, "import_avatar_hide", None)
                    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
                    if importer is not None:
                        try:
                            await importer(data.get("names") or [])
                        except Exception:
                            log.exception("avatar hide import failed")
                    continue
                reactions = getattr(core_state, "reactions", None)
                if reactions is not None and isinstance(msg, dict):
                    try:
                        await reactions.on_client_message(ws, msg)
                    except WebSocketDisconnect:
                        raise           # the client left mid-answer: not an error
                    except Exception:
                        log.exception("game client message failed: %s", str(msg.get("type")))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            manager.disconnect(ws)
            reactions = getattr(core_state, "reactions", None)
            if reactions is not None:
                reactions.detach(ws)

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

    @app.get("/api/overlay/chat-settings")
    async def overlay_chat_settings():
        """Public: the chat overlay polls this (skin, custom CSS version, options, pictures, sounds)."""
        from core.chat_style import CHAT_STYLE

        return CHAT_STYLE.read_settings()

    def _credits():
        eng = getattr(core_state, "credits", None)
        if not eng:
            raise HTTPException(503, "Credits engine not ready")
        return eng

    # Pictures that reactions throw ("img:boot"): built-in + uploaded. Read-only.
    @app.get("/reactions/images/{file_name}")
    async def reaction_image(file_name: str):
        eng = getattr(core_state, "reactions", None)
        lib = getattr(eng, "images", None) if eng else None
        path = lib.file_path(file_name) if lib else None
        if path is None:
            raise HTTPException(404, "No such reaction image")
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------------------
    # Chatter profile pictures (core/avatar_store.py)
    # ------------------------------------------------------------------

    @app.get("/avatars/{platform}/{file_name}")
    async def avatar_file(platform: str, file_name: str):
        store = getattr(core_state, "avatars", None)
        path = store.file_path(platform, file_name) if store else None
        if path is None:
            raise HTTPException(404, "No such picture")
        # the URL carries ?v=<time>, so a new picture gets a new URL
        return FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/api/chatters/avatar")
    async def chatter_avatar(name: str = "", platform: str = "", redirect: int = 0):
        """A chatter's picture by login or display name, for overlays that only know a name
        (reactions, polls, credits). ``redirect=1`` answers with the picture itself."""
        store = getattr(core_state, "avatars", None)
        found = store.find(name, platform) if store else None
        if not found:
            raise HTTPException(404, "No picture for that chatter")
        if redirect:
            target = found["avatar_local"] or found["profile_image_url"]
            if not target:
                raise HTTPException(404, "No picture for that chatter")
            return RedirectResponse(target, status_code=302)
        return found

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
        overlay_files = StaticFiles(directory=str(overlay_dir), html=True)
        # Game plugins' pages answer at /overlay/<file> too (Core's own files win on a name clash),
        # so OBS sources like /overlay/openttd.html keep working after the move into plugins/.
        from core import plugin_manifest

        for extra in plugin_manifest.overlay_dirs():
            overlay_files.all_directories.append(str(extra))
        app.mount("/overlay", overlay_files, name="overlay")

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
        self.plugins = None      # core.plugins.PluginManager (game plugins)
        self.ws_manager: Optional[ConnectionManager] = None
        self.config: dict = {}
        self.build_state = None  # set by create_app
        self.recent_chat: list = []
        self.recent_alerts: list = []
        self.recent_replies: list = []
        self.store = None
        self.market = None
        self.fire_alert = None
        self.test_command = None
        self.test_metrics = None
        self.core = None
        self.reactions = None
        self.chat_games = None
        self.avatars = None
        self.apply_avatar_settings = None
        self.import_avatar_hide = None
