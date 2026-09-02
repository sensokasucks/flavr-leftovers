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
import os
import signal
import sys
import time
from pathlib import Path

if sys.version_info < (3, 10):
    sys.stderr.write(
        "Fridge Stream Core needs Python 3.10 or newer.\n"
        f"This interpreter is {sys.version}\n"
    )
    raise SystemExit(1)

# Ensure project root is on path when run as script
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import uvicorn

    from core.config import ConfigError, ensure_seed_files, load_config, resolve_commands_path
    from core.command_groups import catalog_status, resolve_active_groups
    from core.event_bus import EventBus
    from core.metrics import MetricsAggregator
    from core.permissions import PermissionManager
    from core.command_router import CommandRouter
    from core.models import ChatEvent, ChatReply, ExecuteRequest
    from core.alerts import build_alert
    from core.store import Store
    from core.credits import CreditsEngine
    from adapters.kick import KickAdapter
    from adapters.twitch import TwitchAdapter
    from adapters.youtube import YouTubeAdapter
    from games.minecraft import MinecraftIntegration
    from games.factorio import FactorioIntegration
    from api.server import create_app, CoreState
except ImportError as exc:
    sys.stderr.write(
        f"Missing a Python package: {exc}\n"
        "On Windows, double-click install.bat once.\n"
        "Or run:  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(1) from exc

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

        # Chat log (opt-in) + unified points (SQLite under data/)
        db_path = ROOT / "data" / "stream_core.db"
        self.store = Store(db_path, config.get("points"), config.get("chat_log"))
        self.state.store = self.store
        self.credits = CreditsEngine(config, ROOT)
        self.state.credits = self.credits

        self._metrics_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # Recent chat for overlays that connect mid-stream (newest last)
        self.recent_chat: list[dict] = []
        self.recent_chat_max = 40
        self.recent_alerts: list[dict] = []
        self.recent_alerts_max = 8

    async def start(self) -> None:
        # Wire chat → command router + overlay broadcast
        self.bus.on_chat(self._on_chat)
        self.state.recent_chat = self.recent_chat

        # Wire successful executes → metrics
        self.bus.on_execute(self._on_execute)

        # Wire metrics → game integrations + WS broadcast
        self.bus.on_metrics(self._on_metrics)

        # Start game integrations (all opt-in; more games register the same way)
        mc_cfg = self.config.get("minecraft", {})
        if mc_cfg.get("enabled", False):
            mc = MinecraftIntegration(self.config)
            await mc.start()
            self.games["minecraft"] = mc
        else:
            log.info("Minecraft integration disabled (minecraft.enabled=false)")

        fx_cfg = self.config.get("factorio", {})
        if fx_cfg.get("enabled", False):
            fx = FactorioIntegration(self.config)
            await fx.start()
            self.games["factorio"] = fx
        else:
            log.info("Factorio integration disabled (factorio.enabled=false)")

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

        self.refresh_command_groups()
        self.state.reload_commands = self.reload_commands_live
        self.state.refresh_command_groups = self.refresh_command_groups

        # Outbound chat replies (adapters may send; overlay always shows)
        self.bus.on_reply(self._on_reply)

        # Stream alerts (admin test tab + paid chat)
        self.bus.on_alert(self._on_alert)
        self.state.fire_alert = self.fire_alert
        self.state.recent_alerts = self.recent_alerts

        # Admin integrations test bench
        self.state.test_command = self.test_command
        self.state.test_metrics = self.test_metrics
        self.state.core = self
        self.state.apply_credits = self.apply_credits_config

        # Periodic metrics publish
        self._metrics_task = asyncio.create_task(self._metrics_loop(), name="metrics-loop")
        self._credits_task = asyncio.create_task(self._credits_persist_loop(), name="credits-persist")

        log.info("Stream Core started")

    def refresh_command_groups(self) -> list:
        """Recompute active groups from config + running games (no restart)."""
        extra = self.router.known_groups() if self.router else set()
        groups = resolve_active_groups(self.config, self.games.keys(), extra)
        self.router.set_enabled_groups(groups)
        return sorted(self.router.enabled_groups)

    def reload_commands_live(self) -> dict:
        """Hot-reload commands.json + prefix/player + group enablement."""
        path = resolve_commands_path()
        prefix = (self.config.get("core") or {}).get("command_prefix", "!")
        player = (self.config.get("minecraft") or {}).get("player_name", "Player")
        info = self.router.reload(path, command_prefix=prefix, default_player=player)
        groups = self.refresh_command_groups()
        info["groups_active"] = groups
        log.info(
            "Hot-reloaded commands: %s defs, %s conflicts, groups=%s",
            info.get("loaded"),
            len(info.get("conflicts") or []),
            groups,
        )
        return info

    def apply_credits_config(self) -> dict:
        """Hot-apply credits.enabled / look from in-memory config (no restart)."""
        self.credits.configure(self.config)
        return {
            "enabled": self.credits.enabled,
            "count": len(self.credits.chatters),
        }

    def _credits_perm(self, event, *, need: str | None = None) -> bool:
        from core.models import PermissionLevel
        gate = (need or self.credits.command_permission or "mod").lower()
        if gate == "public":
            return True
        if gate == "mod":
            return self.perms.has_permission(event.user, PermissionLevel.MOD) or event.user.is_mod
        return self.perms.has_permission(event.user, PermissionLevel.ADMIN)

    async def _credits_chat_command(self, event) -> str:
        if not self.credits.enabled:
            return "Credits are off."
        reply, play, needs_mod = self.credits.handle_credits_chat(
            event.message,
            username=event.user.username,
            platform=event.platform.value,
        )
        if needs_mod and not self._credits_perm(event):
            return "Only mods / admins can control the credits roll."
        if play:
            self.credits.set_play(play)
            if self.state.ws_manager:
                await self.state.ws_manager.broadcast(
                    {"type": "credits_play", "data": self.credits.public_play()}
                )
                await self.state.ws_manager.broadcast(
                    {"type": "credits_roster", "data": self.credits.snapshot()}
                )
        return reply

    async def _credits_persist_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=10)
                break
            except asyncio.TimeoutError:
                try:
                    self.credits.save_if_dirty()
                except Exception:
                    log.exception("credits persist failed")

    async def stop(self) -> None:
        self._stop.set()
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
        if getattr(self, "_credits_task", None):
            self._credits_task.cancel()
            try:
                await self._credits_task
            except asyncio.CancelledError:
                pass
            try:
                self.credits.save_if_dirty()
            except Exception:
                log.exception("credits save on stop failed")

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

        try:
            added = self.credits.ingest(event)
            if added and self.state.ws_manager:
                await self.state.ws_manager.broadcast(
                    {"type": "credits_roster", "data": self.credits.snapshot()}
                )
        except Exception:
            log.exception("credits ingest failed")

        # Paid Super Chat / bits / donations → alert overlay
        if event.is_paid:
            await self._alert_from_paid_chat(event)

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

        cmd_def = self.router.find(req.command_name)
        # Core-handled commands (points, help, future polls) — no game fan-out
        if cmd_def and (cmd_def.handler or "game") == "core":
            await self._handle_core_command(event, req, cmd_def)
            return

        log.info(
            "Command OK: %s → %s (by %s)",
            req.command_name, req.template, event.user.username,
        )
        await self.bus.publish_execute(req)

    async def _handle_core_command(self, event: ChatEvent, req: ExecuteRequest, cmd_def) -> None:
        special = (cmd_def.special or req.special or "").lower()
        text = None
        if special == "points_balance":
            try:
                bal = await self.store.get_balance_for_platform(
                    event.platform.value, event.user.id, event.user.username
                )
            except AttributeError:
                # Fallback if store helper not present yet
                bal = None
                try:
                    user = await self.store.find_user_by_identity(
                        event.platform.value, event.user.id
                    )
                    if user:
                        bal = user.get("points")
                except Exception:
                    log.exception("points lookup failed")
            if bal is None:
                text = f"@{event.user.display_name or event.user.username}: no points account yet — chat a bit first!"
            else:
                text = f"@{event.user.display_name or event.user.username}: you have {bal} points"
        elif special == "credit_set":
            if not self.credits.enabled:
                text = "Credits are off."
            elif not self._credits_perm(event):
                text = "Only mods / admins can set credits."
            else:
                text = self.credits.apply_credit_command(
                    event.message,
                    event.platform.value,
                    event.user.username,
                )
                if self.state.ws_manager:
                    await self.state.ws_manager.broadcast(
                        {"type": "credits_roster", "data": self.credits.snapshot()}
                    )
        elif special in ("credits_count", "credits_roll"):
            text = await self._credits_chat_command(event)
        elif special == "help":
            names = sorted({
                c.name for c in self.router.commands.values()
                if c.enabled and (c.group or "core") in self.router.enabled_groups
            })
            prefix = self.router.prefix
            listing = ", ".join(f"{prefix}{n}" for n in names[:30])
            text = f"Commands: {listing}" if listing else "No commands active right now."
        else:
            log.info("Unhandled core special=%s cmd=%s", special, req.command_name)
            return

        self.metrics.record_command()
        reply = ChatReply(
            platform=event.platform,
            message=text,
            reply_to_user=event.user.username,
            reply_to_message_id=event.message_id,
            target_platform=event.platform,
        )
        await self.bus.publish_reply(reply)

    async def _on_reply(self, reply: ChatReply) -> None:
        """Show system replies on the chat overlay; real platform send is adapter-side later."""
        payload = {
            "type": "chat",
            "data": {
                "platform": reply.platform.value,
                "message_id": f"sys-{reply.timestamp}",
                "message": reply.message,
                "timestamp": reply.timestamp,
                "is_system": True,
                "user": {
                    "id": "stream-core",
                    "username": "stream_core",
                    "display_name": "Stream Core",
                    "color": "#53fc18",
                    "is_mod": True,
                    "is_vip": False,
                    "is_subscriber": False,
                    "badges": ["system"],
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
                log.exception("reply WS broadcast failed")
        log.info("[core reply] %s", reply.message)

    async def fire_alert(self, payload: dict) -> dict:
        """Admin test tab and adapters use this."""
        await self.bus.publish_alert(payload)
        return payload

    async def test_command(
        self,
        message: str,
        *,
        username: str = "TestAdmin",
        display_name: str = "",
        platform: str = "kick",
        is_mod: bool = False,
        is_admin: bool = True,
        is_subscriber: bool = False,
        dry_run: bool = True,
    ) -> dict:
        """
        Admin test bench: run a chat command through the real router.

        dry_run=True  → parse + permission + template only (no game.execute)
        dry_run=False → same path as live chat (publish_execute / core handlers)
        """
        from core.models import ChatEvent, ChatUser, Platform

        plat_raw = (platform or "kick").lower().strip()
        try:
            plat = Platform(plat_raw)
        except ValueError:
            plat = Platform.KICK
            plat_raw = "kick"

        user = ChatUser(
            platform=plat,
            id=f"admin-test-{username}",
            username=(username or "TestAdmin").lower().strip(),
            display_name=display_name or username or "TestAdmin",
            is_mod=bool(is_mod or is_admin),
            is_vip=False,
            is_subscriber=bool(is_subscriber),
            badges=["admin"] if is_admin else (["mod"] if is_mod else []),
        )
        # PermissionManager uses config admin/mod sets + temp permits (mod only).
        # For admin tests, temporarily insert into the admin set.
        added_admin = False
        if is_admin and user.username not in self.perms.admins:
            self.perms.admins.add(user.username)
            added_admin = True
        elif is_mod and not is_admin:
            self.perms.grant_temp(user.username, 5)

        event = ChatEvent(
            platform=plat,
            user=user,
            message=(message or "").strip(),
            message_id=f"admin-test-{time.time()}",
        )

        try:
            is_cmd = self.router.parse_message(event)
            if not is_cmd:
                return {
                    "ok": False,
                    "stage": "parse",
                    "error": "not a command (missing prefix or empty)",
                    "prefix": self.router.prefix,
                    "message": event.message,
                }

            req, reason = self.router.try_execute(event)
            if req is None:
                return {
                    "ok": False,
                    "stage": "router",
                    "error": reason or "rejected",
                    "command_name": event.command_name,
                    "args": event.args,
                    "message": event.message,
                }
        finally:
            if added_admin:
                self.perms.admins.discard(user.username)

        cmd_def = self.router.find(req.command_name)
        handler = (cmd_def.handler if cmd_def else "game") or "game"
        group = (cmd_def.group if cmd_def else "") or "core"

        result: dict = {
            "ok": True,
            "stage": "dry_run" if dry_run else "execute",
            "dry_run": dry_run,
            "command_name": req.command_name,
            "args": list(req.args),
            "qty": req.qty,
            "template": req.template,
            "special": req.special,
            "group": group,
            "handler": handler,
            "permission": (cmd_def.permission.value if cmd_def else "public"),
            "message": event.message,
            "user": user.username,
            "platform": plat_raw,
        }

        if dry_run:
            result["note"] = "Dry run — template rendered, game not called"
            return result

        # Live path
        if handler == "core":
            await self._handle_core_command(event, req, cmd_def)
            result["executed"] = {"handler": "core", "success": True}
            return result

        # Fan-out same as _on_execute so we can capture per-game results
        targets = list(self.games.items())
        if group and group in self.games:
            targets = [(group, self.games[group])]

        if not targets:
            result["ok"] = False
            result["error"] = f"no game integration running for group '{group}'"
            result["executed"] = {}
            return result

        executed = {}
        any_ok = False
        for name, game in targets:
            try:
                game_result = await game.execute(req)
                executed[name] = game_result
                if game_result.get("success"):
                    any_ok = True
                    self.metrics.record_command()
            except Exception as e:
                log.exception("[%s] test execute error", name)
                executed[name] = {"success": False, "error": str(e)}

        result["executed"] = executed
        result["ok"] = any_ok
        if not any_ok:
            result["error"] = "all game targets failed or returned success=false"
        return result

    async def test_metrics(
        self,
        *,
        viewers: int = 42,
        cpm: float = 5.0,
        command_rate: float = 1.0,
        power_level: int = 8,
    ) -> dict:
        """
        Push a synthetic MetricsSnapshot to every game integration and overlays.
        Useful for testing Chat Dynamo / power level without live chat volume.
        """
        from core.models import MetricsSnapshot

        power_level = max(0, min(15, int(power_level)))
        snap = MetricsSnapshot(
            viewers=int(viewers),
            viewers_by_platform={"test": int(viewers)},
            cpm=float(cpm),
            command_rate=float(command_rate),
            power_level=power_level,
        )
        # Seed aggregator so Status / overlay build_state stay consistent
        if self.metrics:
            try:
                self.metrics.set_viewers("test", int(viewers))
            except Exception:
                pass

        await self.bus.publish_metrics(snap)
        return {
            "ok": True,
            "metrics": snap.to_dict(),
            "games_notified": list(self.games.keys()),
        }

    async def _on_alert(self, payload: dict) -> None:
        self.recent_alerts.append(payload)
        if len(self.recent_alerts) > self.recent_alerts_max:
            self.recent_alerts = self.recent_alerts[-self.recent_alerts_max :]
        self.state.recent_alerts = self.recent_alerts
        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast({"type": "alert", "data": payload})
            except Exception:
                log.exception("alert WS broadcast failed")
        tag = "TEST" if payload.get("is_test") else payload.get("kind")
        log.info("[alert/%s] %s", tag, payload.get("headline"))
        try:
            added = self.credits.ingest_alert(
                payload.get("kind") or "",
                payload.get("platform") or "",
                payload.get("username") or "",
                display_name=payload.get("display_name") or payload.get("username") or "",
                extra=payload,
            )
            if added and self.state.ws_manager:
                await self.state.ws_manager.broadcast(
                    {"type": "credits_roster", "data": self.credits.snapshot()}
                )
        except Exception:
            log.exception("credits alert tag failed")

    async def _alert_from_paid_chat(self, event: ChatEvent) -> None:
        """Turn Super Chat / bits into an overlay alert (same pipeline as tests)."""
        plat = event.platform.value
        kind = "superchat" if plat == "youtube" else "bits" if plat == "twitch" else "donation"
        currency = event.paid_currency or ("bits" if kind == "bits" else "USD")
        ov = self.config.get("overlay") or {}
        try:
            payload = build_alert(
                kind=kind,
                username=event.user.username,
                display_name=event.user.display_name,
                platform=plat,
                amount=event.paid_amount,
                currency=currency,
                message=event.message,
                duration_ms=int(ov.get("alert_duration_ms") or 6000),
                is_test=False,
            )
        except ValueError:
            return
        await self.bus.publish_alert(payload)

    async def _on_execute(self, req: ExecuteRequest) -> None:
        # Fan-out to every registered game integration that claims this command group
        cmd_def = self.router.find(req.command_name)
        group = (cmd_def.group if cmd_def else "") or ""
        targets = list(self.games.items())
        if group and group in self.games:
            targets = [(group, self.games[group])]

        if not targets:
            log.warning("No game integration for command %s (group=%s)", req.command_name, group)
            return

        for name, game in targets:
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
    ensure_seed_files()
    try:
        config = load_config()
    except ConfigError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        raise SystemExit(1) from exc
    level = config.get("core", {}).get("log_level", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    core = StreamCore(config)
    app = create_app(core.state)

    host = os.environ.get("STREAM_CORE_HOST") or config.get("core", {}).get("host", "127.0.0.1")
    port = int(os.environ.get("STREAM_CORE_PORT") or config.get("core", {}).get("port", 3850))

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
