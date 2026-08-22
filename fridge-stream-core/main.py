#!/usr/bin/env python3
"""
Fridge Stream Core – entry point.

Starts (all chat platforms and Minecraft are opt-in via config):
  - Platform adapters: Kick / Twitch / YouTube
  - Minecraft game integration
  - Command router + metrics aggregator
  - FastAPI HTTP/WS server on the configured port (default 3850)
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn

# Ensure project root is on path when run as script
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config
from core.event_bus import EventBus
from core.metrics import MetricsAggregator
from core.permissions import PermissionManager
from core.command_router import CommandRouter
from core.models import ChatEvent, ExecuteRequest
from core.store import Store
from adapters.kick import KickAdapter
from adapters.twitch import TwitchAdapter
from adapters.youtube import YouTubeAdapter
from games.minecraft import MinecraftIntegration
from api.server import create_app, CoreState

log = logging.getLogger("main")


class StreamCore:
    def __init__(self, config: dict):
        self.config = config
        self.bus = EventBus()
        self.metrics = MetricsAggregator(config)
        self.perms = PermissionManager(config)

        commands_path = ROOT / "config" / "commands.json"
        if not commands_path.exists():
            commands_path = ROOT / "config" / "commands.example.json"

        player = config.get("minecraft", {}).get("player_name", "Player")
        prefix = config.get("core", {}).get("command_prefix", "!")
        self.router = CommandRouter(
            commands_path=commands_path,
            permission_manager=self.perms,
            command_prefix=prefix,
            default_player=player,
        )

        self.adapters = {}
        self.games = {}
        self.state = CoreState()
        self.state.config = config
        self.state.metrics = self.metrics
        self.state.router = self.router
        self.state.adapters = self.adapters
        self.state.games = self.games

        # Chat log + unified points (SQLite under data/)
        db_path = ROOT / "data" / "stream_core.db"
        self.store = Store(db_path, config.get("points"))
        self.state.store = self.store

        self._metrics_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # Recent chat for overlays that connect mid-stream (newest last)
        self.recent_chat: list[dict] = []
        self.recent_chat_max = 40

    async def start(self) -> None:
        # Wire chat → command router + overlay broadcast
        self.bus.on_chat(self._on_chat)
        self.state.recent_chat = self.recent_chat

        # Wire successful executes → metrics
        self.bus.on_execute(self._on_execute)

        # Wire metrics → game integrations + WS broadcast
        self.bus.on_metrics(self._on_metrics)

        # Start game integrations (Minecraft is opt-in)
        mc_cfg = self.config.get("minecraft", {})
        if mc_cfg.get("enabled", False):
            mc = MinecraftIntegration(self.config)
            await mc.start()
            self.games["minecraft"] = mc
        else:
            log.info("Minecraft integration disabled (minecraft.enabled=false)")

        # Start chat adapters (all opt-in — default enabled=false)
        kick_cfg = self.config.get("kick", {})
        if kick_cfg.get("enabled", False):
            kick = KickAdapter(self.config, self.bus, self.metrics)
            await kick.start()
            self.adapters["kick"] = kick
        else:
            log.info("Kick adapter disabled (kick.enabled=false)")

        twitch_cfg = self.config.get("twitch", {})
        if twitch_cfg.get("enabled", False):
            tw = TwitchAdapter(self.config, self.bus, self.metrics)
            await tw.start()
            self.adapters["twitch"] = tw
        else:
            log.info("Twitch adapter disabled (twitch.enabled=false)")

        yt_cfg = self.config.get("youtube", {})
        if yt_cfg.get("enabled", False):
            yt = YouTubeAdapter(self.config, self.bus, self.metrics)
            await yt.start()
            self.adapters["youtube"] = yt
        else:
            log.info("YouTube adapter disabled (youtube.enabled=false)")

        # Periodic metrics publish
        self._metrics_task = asyncio.create_task(self._metrics_loop(), name="metrics-loop")

        log.info("Stream Core started")

    async def stop(self) -> None:
        self._stop.set()
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        for adapter in self.adapters.values():
            await adapter.stop()
        for game in self.games.values():
            await game.stop()
        log.info("Stream Core stopped")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_chat(self, event: ChatEvent) -> None:
        # Always push to chat overlay clients (emotes live in the raw message text)
        payload = {
            "type": "chat",
            "data": {
                "platform": event.platform.value,
                "message_id": event.message_id,
                "message": event.message,
                "timestamp": event.timestamp,
                "user": {
                    "id": event.user.id,
                    "username": event.user.username,
                    "display_name": event.user.display_name,
                    "color": event.user.color,
                    "is_mod": event.user.is_mod,
                    "is_vip": event.user.is_vip,
                    "is_subscriber": event.user.is_subscriber,
                    "badges": event.user.badges,
                },
            },
        }
        self.recent_chat.append(payload["data"])
        if len(self.recent_chat) > self.recent_chat_max:
            self.recent_chat = self.recent_chat[-self.recent_chat_max:]

        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast(payload)
            except Exception:
                log.exception("chat WS broadcast failed")

        # Mark command flag before logging so history knows
        is_cmd = self.router.parse_message(event)

        # Persist chat + award in-house points
        try:
            result = await self.store.process_chat(event)
            if result.get("awarded"):
                log.debug(
                    "points +%s → user %s (bal %s)",
                    result["awarded"],
                    result["user_id"],
                    result.get("balance"),
                )
        except Exception:
            log.exception("store.process_chat failed")

        if not is_cmd:
            return

        req, reason = self.router.try_execute(event)
        if req is None:
            if reason and reason not in ("not a command", "permit handled"):
                log.info("Command rejected (%s): %s", reason, event.message)
            return

        log.info(
            "Command OK: %s → %s (by %s)",
            req.command_name, req.template, event.user.username,
        )
        await self.bus.publish_execute(req)

    async def _on_execute(self, req: ExecuteRequest) -> None:
        # Fan-out to every registered game integration
        for name, game in self.games.items():
            try:
                result = await game.execute(req)
                if result.get("success"):
                    self.metrics.record_command()
                    log.info("[%s] executed %s", name, req.command_name)
                else:
                    log.warning("[%s] execute failed: %s", name, result.get("error"))
            except Exception:
                log.exception("[%s] execute error", name)

    async def _on_metrics(self, snap) -> None:
        for game in self.games.values():
            try:
                await game.on_metrics(snap)
            except Exception:
                log.exception("game on_metrics error")

        # Push rich update to connected WebSocket clients (overlays)
        if self.state.ws_manager:
            if getattr(self.state, "build_state", None):
                try:
                    payload = await self.state.build_state()
                    await self.state.ws_manager.broadcast(payload)
                    return
                except Exception:
                    log.exception("build_state for WS failed")
            # fallback
            await self.state.ws_manager.broadcast({
                "type": "update",
                "metrics": {
                    "viewers": snap.viewers,
                    "cpm": snap.cpm,
                    "powerLevel": snap.power_level,
                },
                "stats": {},
            })

    async def _metrics_loop(self) -> None:
        while not self._stop.is_set():
            snap = self.metrics.snapshot()
            await self.bus.publish_metrics(snap)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass


async def _run() -> None:
    config = load_config()
    level = config.get("core", {}).get("log_level", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    core = StreamCore(config)
    app = create_app(core.state)

    host = config.get("core", {}).get("host", "127.0.0.1")
    port = int(config.get("core", {}).get("port", 3850))

    # Start Core background work
    await core.start()

    # Run uvicorn in the same event loop
    uvi_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=level.lower(),
        loop="asyncio",
    )
    server = uvicorn.Server(uvi_config)

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows
            pass

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        [serve_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    server.should_exit = True
    await core.stop()
    for t in pending:
        t.cancel()


def main():
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
