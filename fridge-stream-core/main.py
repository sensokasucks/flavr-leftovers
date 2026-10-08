#!/usr/bin/env python3
"""
Fridge Stream Core – entry point.

Starts (all chat platforms and games are opt-in via config):
  - Platform adapters: Kick / Twitch / YouTube
  - Game plugins found in plugins/ (Minecraft, Factorio, Granvir, OpenTTD from the games pack)
  - Command router + metrics aggregator
  - FastAPI HTTP/WS server on the configured port (default 3850)
"""

from __future__ import annotations

import asyncio
import copy
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

    from core.config import (
        DEFAULTS,
        ConfigError,
        ensure_seed_files,
        load_config,
        resolve_commands_path,
        resolve_config_path,
    )
    from core.command_groups import catalog_status, resolve_active_groups
    from core.event_bus import EventBus
    from core.metrics import MetricsAggregator
    from core.permissions import PermissionManager
    from core.command_router import CommandRouter
    from core.models import ChatEvent, ChatReply, ExecuteRequest
    from core.alerts import build_alert
    from core.store import Store
    from core.local_guard import is_placeholder_token, resolve_admin_token
    from core.credits import CreditsEngine
    from core.avatar_store import AvatarStore
    from core.red_flags import RedFlags, matching_recent
    from core.market import MarketTape
    from core.reactions import ReactionEngine
    from core.reaction_images import ReactionImages
    from core.chat_games import ChatGames
    from adapters.kick import KickAdapter
    from adapters.twitch import TwitchAdapter
    from adapters.youtube import YouTubeAdapter
    from core import plugin_manifest
    from core.plugins import PluginManager
    from api.server import create_app, CoreState
except ImportError as exc:
    sys.stderr.write(
        f"Missing a Python package: {exc}\n"
        "On Windows, double-click install.bat once.\n"
        "Or run:  python -m pip install -r requirements.txt\n"
    )
    raise SystemExit(1) from exc

log = logging.getLogger("main")

# Chat platforms Core can start, stop and reconnect while running
PLATFORM_ADAPTERS = {
    "kick": KickAdapter,
    "twitch": TwitchAdapter,
    "youtube": YouTubeAdapter,
}


def default_player(config: dict) -> str:
    """{player} in command templates: core.player_name, else a game plugin's player_name."""
    name = str((config.get("core") or {}).get("player_name") or "").strip()
    if name:
        return name
    for pid in plugin_manifest.installed_ids():
        name = str((config.get(pid) or {}).get("player_name") or "").strip()
        if name:
            return name
    return "Player"


class StreamCore:
    def __init__(self, config: dict):
        self.config = config
        self.bus = EventBus()
        self.metrics = MetricsAggregator(config)
        self.perms = PermissionManager(config)

        commands_path = ROOT / "config" / "commands.json"
        if not commands_path.exists():
            commands_path = ROOT / "config" / "commands.example.json"

        player = default_player(config)
        prefix = config.get("core", {}).get("command_prefix", "!")
        self.router = CommandRouter(
            commands_path=commands_path,
            permission_manager=self.perms,
            command_prefix=prefix,
            default_player=player,
            default_commands=plugin_manifest.default_commands,
        )

        self.adapters = {}
        # Platform config sections as last applied, so a save only reconnects what changed
        self._platform_applied: dict[str, dict] = {}
        self._platform_lock = asyncio.Lock()
        # Kick chatroom ids left over from a channel we switched away from
        self._kick_stale_rooms: set[str] = set()
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
        self.market = MarketTape(config, listings_path=ROOT / "data" / "market_tickers.json")
        self.state.market = self.market
        # Game plugins (plugins/<id>/): loaded now so their routes exist, started in start()
        self.plugins = PluginManager(
            get_config=lambda: self.state.config or self.config,
            games=self.games,
            market=self.market,
            store=self.store,
            bus=self.bus,
            broadcast=self._ws_broadcast,
            root=ROOT,
        )
        self.plugins.load_all()
        self.state.plugins = self.plugins
        # Chat reactions (emoji / commands → Stream Rooms or fallback overlay)
        self.reactions = ReactionEngine(
            get_config=lambda: self.state.config or self.config,
            store=self.store,
            perms=self.perms,
            data_dir=ROOT / "data",
            reply=self._reaction_reply,
            say=self._reaction_say,
            broadcast=self._ws_broadcast,
            groups_active=lambda: self.router.enabled_groups,
            command_prefix=lambda: self.router.prefix,
            images=ReactionImages(ROOT / "overlay" / "assets" / "reactions", ROOT / "data" / "reaction_images"),
        )
        self.state.reactions = self.reactions
        # Chat games + crowd moments (combos, hype, polls, predictions, slots, heists ...)
        self.chat_games = ChatGames(
            get_config=lambda: self.state.config or self.config,
            store=self.store,
            perms=self.perms,
            reactions=self.reactions,
            data_dir=ROOT / "data",
            config_dir=ROOT / "config",
            reply=self._games_reply,
            broadcast=self._ws_broadcast,
            groups_active=lambda: self.router.enabled_groups,
            command_prefix=lambda: self.router.prefix,
        )
        self.state.chat_games = self.chat_games
        self.credits.extra = self._credits_extra
        # Chatter profile pictures saved by Core and served at /avatars/... (core/avatar_store.py)
        self.avatars = AvatarStore()
        self._avatars_cfg: dict = {}
        self.avatars.configure(config.get("avatars") or {})
        self._avatars_cfg = copy.deepcopy(config.get("avatars") or {})
        self.state.avatars = self.avatars
        self.state.apply_avatar_settings = self.apply_avatar_settings
        self.state.import_avatar_hide = self.import_avatar_hide
        # Red flags: phrases that put a chatter on a list kept off every overlay (core/red_flags.py)
        self.red_flags = RedFlags(self.store, config.get("red_flags"))
        self.state.red_flags = self.red_flags
        self.state.red_flag_hide = self.hide_flagged

        self._metrics_task: asyncio.Task | None = None
        self._market_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # Recent chat for overlays that connect mid-stream (newest last)
        self.recent_chat: list[dict] = []
        self.recent_chat_max = 40
        self.recent_alerts: list[dict] = []
        self.recent_alerts_max = 8
        # Recent command replies (the reply screen / replies overlay catch up on connect)
        self.recent_replies: list[dict] = []
        self.recent_replies_max = 20

    async def start(self) -> None:
        # Wire chat → command router + overlay broadcast
        self.bus.on_chat(self._on_chat)
        self.state.recent_chat = self.recent_chat
        self.state.recent_replies = self.recent_replies

        # Wire successful executes → metrics
        self.bus.on_execute(self._on_execute)

        # Wire metrics → game integrations + WS broadcast
        self.bus.on_metrics(self._on_metrics)

        # Start the enabled game plugins (all opt-in; a broken one is logged and skipped)
        await self.plugins.start_enabled()

        # Start chat adapters (all opt-in — default enabled=false)
        for name in PLATFORM_ADAPTERS:
            await self._start_platform(name)

        self.refresh_command_groups()
        self.state.reload_commands = self.reload_commands_live
        self.state.refresh_command_groups = self.refresh_command_groups

        # Outbound chat replies (adapters may send; overlay always shows)
        self.bus.on_reply(self._on_reply)

        # Stream alerts (admin test tab + paid chat)
        self.bus.on_alert(self._on_alert)

        # Late user info (Kick profile pictures) → overlays + recent chat history
        self.bus.on_user_update(self._on_user_update)
        self.state.fire_alert = self.fire_alert
        self.state.recent_alerts = self.recent_alerts

        # Admin integrations test bench
        self.state.test_command = self.test_command
        self.state.test_metrics = self.test_metrics
        self.state.core = self
        self.state.apply_credits = self.apply_credits_config
        self.state.apply_platforms = self.apply_platforms

        # Periodic metrics publish
        self._metrics_task = asyncio.create_task(self._metrics_loop(), name="metrics-loop")
        self._credits_task = asyncio.create_task(self._credits_persist_loop(), name="credits-persist")
        self._market_task = asyncio.create_task(self._market_loop(), name="market-tape")
        self._games_task = asyncio.create_task(self._games_loop(), name="chat-games")
        if (self.config.get("core") or {}).get("watch_config", True):
            self._config_watch_task = asyncio.create_task(
                self._config_watch_loop(), name="config-watch"
            )

        log.info("Stream Core started")

    # ------------------------------------------------------------------
    # Chat platforms (hot-applied, no restart)
    # ------------------------------------------------------------------

    async def _start_platform(self, name: str) -> None:
        section = self.config.get(name) or {}
        if not section.get("enabled", False):
            log.info("%s adapter disabled (%s.enabled=false)", name.title(), name)
            self._platform_applied[name] = copy.deepcopy(section)
            return
        adapter = PLATFORM_ADAPTERS[name](self.config, self.bus, self.metrics)
        try:
            await adapter.start()
        finally:
            # Kick may write a resolved chatroom_id back into config while starting
            self._platform_applied[name] = copy.deepcopy(self.config.get(name) or {})
        if getattr(adapter, "_running", False):
            self.adapters[name] = adapter
        else:
            # start() already logged why (channel not set, chatroom lookup failed, ...)
            await adapter.stop()

    async def _stop_platform(self, name: str) -> None:
        adapter = self.adapters.pop(name, None)
        if adapter:
            try:
                await adapter.stop()
            except Exception:
                log.exception("%s adapter stop failed", name)
        self.metrics.clear_viewers(name)

    @staticmethod
    def _platform_changed(new: dict, old: dict | None) -> bool:
        if old is None:
            return True
        # chatroom_id is a cached lookup: gaining one is a change, losing one is not
        strip = lambda d: {k: v for k, v in d.items() if k != "chatroom_id"}
        if strip(new) != strip(old):
            return True
        return new.get("chatroom_id") not in (None, "", old.get("chatroom_id"))

    def _forget_kick_room(self, section: dict, old: dict | None) -> dict:
        """Drop a chatroom_id that belongs to the previous Kick channel."""
        room = section.get("chatroom_id")
        if old is not None and section.get("channel_slug") != old.get("channel_slug"):
            if room not in (None, "") and room == old.get("chatroom_id"):
                self._kick_stale_rooms.add(str(room))
        if room in (None, "") or str(room) not in self._kick_stale_rooms:
            return section
        section = {k: v for k, v in section.items() if k != "chatroom_id"}
        self.config["kick"] = section
        try:
            from core.config import save_config

            disk = load_config()
            kick = dict(disk.get("kick") or {})
            if str(kick.get("chatroom_id")) == str(room):
                kick.pop("chatroom_id", None)
                disk["kick"] = kick
                save_config(disk)
        except Exception:
            log.exception("Could not clear old kick.chatroom_id from config.yaml")
        return section

    async def apply_platforms(self, force: tuple | list = ()) -> dict:
        """Reconnect only the chat platforms whose config changed (or in ``force``)."""
        async with self._platform_lock:
            self._sync_live_config()
            changed = []
            for name in PLATFORM_ADAPTERS:
                section = self.config.get(name) or {}
                old = self._platform_applied.get(name)
                if name == "kick":
                    section = self._forget_kick_room(section, old)
                if name not in force and not self._platform_changed(section, old):
                    continue
                log.info("Applying %s settings (reconnecting)", name)
                await self._stop_platform(name)
                try:
                    await self._start_platform(name)
                except Exception:
                    log.exception("%s adapter failed to start", name)
                changed.append(name)
            return {"changed": changed, "running": sorted(self.adapters)}

    def apply_live_config(self) -> None:
        """Hot-apply the parts of config that do not need a restart."""
        self.refresh_command_groups()
        self.apply_credits_config()
        self.plugins.apply_config(self.config)

    async def _config_watch_loop(self) -> None:
        """Pick up hand edits to config.yaml (Notepad, wizard.py) without a restart."""
        path = resolve_config_path()
        last = path.stat().st_mtime if path and path.exists() else None
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                break
            except asyncio.TimeoutError:
                pass
            try:
                path = resolve_config_path()
                mtime = path.stat().st_mtime if path and path.exists() else None
                if mtime is None or mtime == last:
                    continue
                last = mtime
                try:
                    fresh = load_config()
                except ConfigError as exc:
                    log.warning("config.yaml changed but could not be read; keeping current settings. %s", exc)
                    continue
                self.state.config = fresh
                self.apply_live_config()
                info = await self.apply_platforms()
                if info["changed"]:
                    log.info("config.yaml changed: reconnected %s", ", ".join(info["changed"]))
            except Exception:
                log.exception("config watch failed")

    def _sync_live_config(self) -> None:
        """Admin saves replace state.config with a fresh dict; follow it."""
        live = getattr(self.state, "config", None)
        if isinstance(live, dict) and live is not self.config:
            self.config = live

    def refresh_command_groups(self) -> list:
        """Recompute active groups from config + running games (no restart)."""
        self._sync_live_config()
        extra = self.router.known_groups() if self.router else set()
        groups = resolve_active_groups(self.config, self.games.keys(), extra)
        self.router.set_enabled_groups(groups)
        return sorted(self.router.enabled_groups)

    def reload_commands_live(self) -> dict:
        """Hot-reload commands.json + prefix/player + group enablement."""
        path = resolve_commands_path()
        prefix = (self.config.get("core") or {}).get("command_prefix", "!")
        player = default_player(self.config)
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
        self._sync_live_config()
        self.credits.configure(self.config)
        return {
            "enabled": self.credits.enabled,
            "count": len(self.credits.chatters),
        }

    async def _market_loop(self) -> None:
        """Walk preview / live prices so overlay charts have a series."""
        while not self._stop.is_set():
            delay = max(1.0, float(getattr(self.market, "tick_sec", 5) or 5))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                try:
                    self.market.tick()
                    now = time.time()
                    last = getattr(self, "_steam_poll_at", 0)
                    poll_every = float(getattr(self.market, "steam_poll_sec", 1800) or 1800)
                    if now - last >= poll_every:
                        self._steam_poll_at = now
                        await self.market.poll_steam()
                    try:
                        await self.market.tick_chatter(self.store)
                    except Exception:
                        log.exception("chatter tape tick failed")
                except Exception:
                    log.exception("market tape tick failed")

    async def _games_loop(self) -> None:
        """Timers for chat games (poll / prediction / heist ends, hype meter, countdowns)."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5)
                break
            except asyncio.TimeoutError:
                try:
                    await self.chat_games.tick()
                    # a new rating (or title) changes the end credits: resend the roster
                    line = self._credits_extra().get("rating_line", "") if self.credits.enabled else ""
                    if line != getattr(self, "_last_rating_line", "") and self.state.ws_manager:
                        self._last_rating_line = line
                        self.state.ws_manager.push_roster(self.credits.snapshot)
                except Exception:
                    log.exception("chat games tick failed")

    def _credits_extra(self) -> dict:
        """Chat games bits for the end credits: regulars' titles and tonight's rating."""
        games = self.chat_games
        out = {"titles": {}, "rating_line": ""}
        try:
            for c in self.credits.chatters.values():
                t = games.title_by_name(c.platform, c.username)
                if t:
                    out["titles"][c.key] = t
            s = games._stream
            if s and games.on("rate"):
                out["rating_line"] = games.rate.credits_line(s.get("id"))
        except Exception:
            log.exception("credits extras failed")
        return out

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
        if getattr(self, "_market_task", None):
            self._market_task.cancel()
            try:
                await self._market_task
            except asyncio.CancelledError:
                pass
        if getattr(self, "_games_task", None):
            self._games_task.cancel()
            try:
                await self._games_task
            except asyncio.CancelledError:
                pass
            self.chat_games.tick_save()
        if getattr(self, "_config_watch_task", None):
            self._config_watch_task.cancel()
            try:
                await self._config_watch_task
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

        for name in list(self.adapters):
            await self._stop_platform(name)
        self.avatars.stop()
        for game in self.games.values():
            await game.stop()
        log.info("Stream Core stopped")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_chat(self, event: ChatEvent) -> None:
        # Red-flagged chatters (or the line that flags them) never reach an overlay or Stream Rooms
        self.red_flags.configure((getattr(self.state, "config", None) or self.config).get("red_flags"))
        try:
            flagged = await self.red_flags.check(event)
        except Exception:
            log.exception("red flag check failed")
            flagged = None
        if flagged is not None:
            await self._on_flagged_chat(event, flagged)
            return
        # Regulars' titles ride along on the chat packet (name tags in Stream Rooms)
        try:
            await self.chat_games.observe_user(event)
        except Exception:
            log.exception("chat games attendance failed")
        title = self.chat_games.title_for(event.user)
        await self.apply_avatar_settings()
        plat = event.platform.value
        hidden = self.avatars.is_hidden(plat, event.user.username, event.user.display_name)
        picture = None if hidden else event.user.profile_image_url
        local = "" if hidden else self.avatars.local_url(plat, str(event.user.id))
        # Always push to chat overlay clients (emotes live in the raw message text)
        payload = {
            "type": "chat",
            "data": {
                "platform": event.platform.value,
                "message_id": event.message_id,
                "message": event.message,
                "timestamp": event.timestamp,
                # emote ranges (Twitch native + BTTV/FFZ/7TV); Kick uses inline tokens
                "emotes": list(event.emotes or []),
                "user": {
                    "id": event.user.id,
                    "username": event.user.username,
                    "display_name": event.user.display_name,
                    "color": event.user.color,
                    "profile_image_url": picture,
                    # Core's own copy (/avatars/...), "" until it's downloaded
                    "avatar_local": local,
                    "is_mod": event.user.is_mod,
                    "is_vip": event.user.is_vip,
                    "is_subscriber": event.user.is_subscriber,
                    "badges": event.user.badges,
                    "title": title,
                },
                # a reply made with the platform's reply button: who it answers and a short quote
                "reply_to": event.reply_to,
                # Super Chat / Kicks / Bits: the overlay and Stream Rooms mark these
                "is_paid": event.is_paid,
                "paid_amount": event.paid_amount,
                "paid_currency": event.paid_currency,
                # Twitch channel-point styles: "highlighted" / "gigantified" / "animated" / None
                "highlight": event.highlight,
            },
        }
        self.recent_chat.append(payload["data"])
        if not hidden:
            self.avatars.note(plat, str(event.user.id), event.user.profile_image_url or "",
                              event.user.username, event.user.display_name, on_ready=self._avatar_ready)
        if len(self.recent_chat) > self.recent_chat_max:
            del self.recent_chat[:-self.recent_chat_max]

        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast(payload)
            except Exception:
                log.exception("chat WS broadcast failed")

        try:
            added = self.credits.ingest(event)
            if added and self.state.ws_manager:
                # throttled, and only to the credits overlay / Credits tab (api/server.py)
                self.state.ws_manager.push_roster(self.credits.snapshot)
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

        # Chat reactions (emoji anywhere; !commands the router doesn't own), then chat games
        # (they watch every message for combos / hype; commands nobody else took)
        name = (event.command_name or "").lower() if is_cmd else ""
        router_owns = bool(is_cmd and (name == "permit" or self.router.find(name)))
        taken = False
        try:
            taken = await self.reactions.handle_chat(event, router_owns_command=router_owns)
        except Exception:
            log.exception("reactions failed")
        try:
            if await self.chat_games.handle_chat(event, command_taken=taken or router_owns):
                taken = True
        except Exception:
            log.exception("chat games failed")
        if taken:
            self.metrics.record_command()
            return

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

    async def _handle_market_command(self, event: ChatEvent, special: str) -> str:
        tape = self.market
        store = self.store
        parts = (event.message or "").split()
        if special == "market_tickers":
            snap = tape.snapshot() if tape else {"instruments": []}
            bits = [
                f"{it['symbol']} {it['price']:.2f}"
                for it in (snap.get("instruments") or [])[:8]
            ]
            return "Tickers: " + (", ".join(bits) if bits else "none listed")
        uid = await store.get_or_create_user(
            event.platform.value, event.user.id, event.user.username, event.user.display_name
        )
        if special == "market_portfolio":
            holds = await store.holdings_for_user(uid)
            if not holds:
                return f"@{event.user.username}: no shares yet. Try !buy MINECRAF 20"
            bits = []
            for h in holds:
                px = (tape.quote(h["symbol"]) or {}).get("price", 0) if tape else 0
                bits.append(f"{h['symbol']} {h['milli_shares']/1000:.2f}sh @ {float(px):.2f}")
            return f"@{event.user.username}: " + ", ".join(bits)
        if len(parts) < 2:
            return "Usage: !buy SYMBOL POINTS   or   !sell SYMBOL QTY|all"
        symbol = parts[1].upper()
        inst = tape.quote(symbol) if tape else None
        if not inst or inst.get("status") != "listed":
            return f"{symbol} is not listed (or is hidden)."
        price = float(inst.get("price") or 0) or 1.0
        user = await store.get_user(uid)
        bal = int((user or {}).get("points") or 0)
        if special == "market_buy":
            if len(parts) < 3:
                return "Usage: !buy SYMBOL POINTS"
            try:
                spend = int(float(parts[2]))
            except ValueError:
                return "Points must be a number."
            if spend <= 0:
                return "Spend at least 1 point."
            if bal < spend:
                return f"@{event.user.username}: need {spend} points, have {bal}."
            shares = spend / price
            await store.adjust_points(uid, -spend, f"buy {symbol}", "market")
            nxt = await store.adjust_holding(uid, symbol, int(round(shares * 1000)))
            if tape:
                tape.apply_trade_impact(symbol, spend, side="buy")
            return f"@{event.user.username}: bought {shares:.3f} {symbol} @ {price:.2f} ({nxt/1000:.3f} sh)"
        raw = parts[2] if len(parts) > 2 else "all"
        holds = {h["symbol"]: h["milli_shares"] for h in await store.holdings_for_user(uid)}
        have = int(holds.get(symbol) or 0)
        if have <= 0:
            return f"@{event.user.username}: no {symbol} shares."
        if raw.lower() == "all":
            sell_milli = have
        else:
            try:
                sell_milli = int(round(float(raw) * 1000))
            except ValueError:
                return "Qty must be a number or all."
        sell_milli = max(0, min(have, sell_milli))
        credit = int(round((sell_milli / 1000.0) * price))
        await store.adjust_holding(uid, symbol, -sell_milli)
        if credit:
            await store.adjust_points(uid, credit, f"sell {symbol}", "market")
        if tape:
            tape.apply_trade_impact(symbol, credit, side="sell")
        return f"@{event.user.username}: sold {sell_milli/1000:.3f} {symbol} for {credit} pts"

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
            else:
                from core.models import PermissionLevel
                need = (self.credits.command_permission or "mod").lower()
                if need == "public":
                    ok = True
                elif need == "mod":
                    ok = self.perms.has_permission(event.user, PermissionLevel.MOD) or event.user.is_mod
                else:
                    ok = self.perms.has_permission(event.user, PermissionLevel.ADMIN)
                if not ok:
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
        elif special == "credits_count":
            text = f"Credits roster: {len(self.credits.chatters)} unique chatters"
        elif special in ("market_buy", "market_sell", "market_tickers", "market_portfolio"):
            text = await self._handle_market_command(event, special)
        elif special == "help":
            names = sorted({
                c.name for c in self.router.commands.values()
                if c.enabled and (c.group or "core") in self.router.enabled_groups
            } | set(self._extra_command_names()))
            prefix = self.router.prefix
            listing = ", ".join(f"{prefix}{n}" for n in names[:45])
            text = f"Commands: {listing}" if listing else "No commands active right now."
        else:
            log.info("Unhandled core special=%s cmd=%s", special, req.command_name)
            return

        self.metrics.record_command()
        reply = ChatReply(
            platform=event.platform,
            message=text,
            reply_to_user=event.user.display_name or event.user.username,
            reply_to_message_id=event.message_id,
            target_platform=event.platform,
        )
        await self.bus.publish_reply(reply)

    def _extra_command_names(self) -> list:
        """Reaction + chat game commands that are on (for !help)."""
        out = []
        try:
            if self.reactions.active():
                for e in self.reactions.cfg["entries"]:
                    if self.reactions.entry_usable(e)[0]:
                        out.extend(e["commands"][:1])
            games = self.chat_games.command_names()
            out.extend(n for n in games if not n.isdigit())
        except Exception:
            log.exception("help listing failed")
        return out

    async def _games_reply(self, event, text: str) -> None:
        """Chat games answer through the same API-free reply path as commands."""
        from core.models import Platform
        if event is None:
            try:
                plat = Platform(next(iter(self.adapters)))
            except (StopIteration, ValueError):
                plat = Platform.KICK
            await self.bus.publish_reply(ChatReply(platform=plat, message=text, source="chat_game"))
            return
        await self.bus.publish_reply(ChatReply(
            platform=event.platform,
            message=text,
            reply_to_user=event.user.display_name or event.user.username,
            reply_to_message_id=event.message_id,
            target_platform=event.platform,
            source="chat_game",
        ))

    async def _ws_broadcast(self, payload: dict) -> None:
        if self.state.ws_manager:
            await self.state.ws_manager.broadcast(payload)

    async def _reaction_reply(self, event: ChatEvent, text: str) -> None:
        await self.bus.publish_reply(ChatReply(
            platform=event.platform,
            message=text,
            reply_to_user=event.user.display_name or event.user.username,
            reply_to_message_id=event.message_id,
            target_platform=event.platform,
            source="reaction",
        ))

    async def _reaction_say(self, text: str, platform: str | None = None) -> None:
        """A line from the game (Stream Rooms) posted through Core's reply path."""
        from core.models import Platform
        try:
            plat = Platform(platform) if platform else Platform(next(iter(self.adapters)))
        except (StopIteration, ValueError):
            plat = Platform.KICK
        await self.bus.publish_reply(ChatReply(platform=plat, message=text, source="game"))

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
            del self.recent_chat[:-self.recent_chat_max]
        # Core has no chat-write login for Kick / YouTube, so this broadcast is how viewers
        # see an answer: the replies overlay, and the Stream Rooms reply screen.
        data = {
            "id": f"reply-{reply.timestamp}",
            "message": reply.message,
            "platform": reply.platform.value,
            "reply_to_user": reply.reply_to_user or "",
            "reply_to_message_id": reply.reply_to_message_id or "",
            "source": reply.source or "command",
            "timestamp": reply.timestamp,
            "posted_to_chat": False,
        }
        self.recent_replies.append(data)
        if len(self.recent_replies) > self.recent_replies_max:
            del self.recent_replies[: -self.recent_replies_max]
        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast(payload)
                await self.state.ws_manager.broadcast({"type": "reply", "data": data})
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
        # Keys are platform-scoped (see core/permissions.py), so use the
        # platform:id key — works for YouTube too.
        test_key = f"{plat_raw}:{user.id}".lower()
        added_admin = False
        if is_admin and test_key not in self.perms.admins:
            self.perms.admins.add(test_key)
            added_admin = True
        elif is_mod and not is_admin:
            self.perms.grant_temp(test_key, 5)

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
                self.perms.admins.discard(test_key)

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

    async def _on_flagged_chat(self, event: ChatEvent, flagged: dict) -> None:
        """A red-flagged chatter: saved in the chat log (when it is on), shown nowhere, no points."""
        self.router.parse_message(event)      # marks is_command for the log
        try:
            await self.store.process_chat(event, award=False)
        except Exception:
            log.exception("store.process_chat failed")
        if flagged.get("new"):
            u = event.user
            await self.hide_flagged(event.platform.value, str(u.id or ""), u.username, u.display_name)

    async def hide_flagged(self, platform: str, user_id: str, username: str, display_name: str = "") -> int:
        """Someone was just red-flagged: take their lines off the chat overlay and Stream Rooms
        (``chat_user_hidden``), out of the catch-up history and out of the credits. Returns how
        many recent lines went."""
        gone = matching_recent(self.recent_chat, platform, user_id, username, display_name)
        for item in gone:
            self.recent_chat.remove(item)
        try:
            if self.credits.forget(platform, username, display_name) and self.state.ws_manager:
                self.state.ws_manager.push_roster(self.credits.snapshot)
        except Exception:
            log.exception("credits forget failed")
        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast({"type": "chat_user_hidden", "data": {
                    "platform": platform, "id": user_id, "username": username,
                    "display_name": display_name or username}})
            except Exception:
                log.exception("chat_user_hidden WS broadcast failed")
        return len(gone)

    async def _on_user_update(self, payload: dict) -> None:
        """{"platform", "id", "username", "profile_image_url"} → WS ``type:user_update``.
        Core adds ``avatar_local`` (its own copy) and drops hidden chatters' pictures."""
        plat = str(payload.get("platform") or "")
        uid = str(payload.get("id") or "")
        await self.apply_avatar_settings()
        if self.avatars.is_hidden(plat, str(payload.get("username") or ""), str(payload.get("display_name") or "")):
            return
        payload["avatar_local"] = self.avatars.local_url(plat, uid)
        self.avatars.note(plat, uid, str(payload.get("profile_image_url") or ""),
                          str(payload.get("username") or ""), str(payload.get("display_name") or ""),
                          on_ready=self._avatar_ready)
        await self._send_user_update(payload)

    async def _send_user_update(self, payload: dict) -> None:
        plat = payload.get("platform")
        uid = str(payload.get("id") or "")
        for item in self.recent_chat:
            user = item.get("user") or {}
            if item.get("platform") == plat and str(user.get("id") or "") == uid:
                for k in ("profile_image_url", "avatar_local"):
                    if k in payload:
                        user[k] = payload.get(k)
        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast({"type": "user_update", "data": payload})
            except Exception:
                log.exception("user_update WS broadcast failed")

    async def _avatar_ready(self, platform: str, user_id: str, local: str) -> None:
        """Core saved a chatter's picture: overlays and Stream Rooms switch to the local copy."""
        info = self.avatars.entry(platform, user_id)
        await self._send_user_update({"platform": platform, "id": user_id, "username": info.get("login") or "",
                                      "profile_image_url": info.get("url") or "", "avatar_local": local})

    async def import_avatar_hide(self, names: list) -> int:
        """Stream Rooms hands over its "hide pictures for" names: add the new ones to
        ``avatars.hide`` in config.yaml (merge, nothing removed). Returns how many were new."""
        from core.avatar_store import parse_hide
        from core.config import save_config

        try:
            cfg = load_config()         # merge into what is on disk, like every config save
        except Exception:
            cfg = copy.deepcopy(getattr(self.state, "config", None) or self.config)
        section = dict(cfg.get("avatars") or {})
        have = list(section.get("hide") or [])
        known = set(parse_hide(have))
        added = 0
        for p, n in parse_hide(names[:500] if isinstance(names, list) else []):
            if (p, n) in known or ("", n) in known:
                continue
            have.append(f"{p}:{n}" if p else n)
            known.add((p, n))
            added += 1
        if not added:
            return 0
        section["hide"] = have
        cfg["avatars"] = section
        self.state.config = cfg
        try:
            save_config(cfg)
        except Exception:
            log.exception("could not save avatars.hide")
        log.info("Added %d name(s) from Stream Rooms to the picture hide list", added)
        await self.apply_avatar_settings()
        return added

    async def apply_avatar_settings(self) -> None:
        """Follow ``avatars:`` in config (admin save, hand edit). Chatters who just went on the
        hide list lose their picture everywhere right away."""
        cfg = (getattr(self.state, "config", None) or self.config).get("avatars") or {}
        if cfg == self._avatars_cfg:
            return
        before = set(self.avatars.hide_list)
        self.avatars.configure(cfg)
        self._avatars_cfg = copy.deepcopy(cfg)
        if set(self.avatars.hide_list) - before:
            for u in self.avatars.known_users():
                if self.avatars.is_hidden(u["platform"], u["login"], u["name"]):
                    await self._send_user_update({"platform": u["platform"], "id": u["id"], "hidden": True,
                                                  "profile_image_url": "", "avatar_local": ""})

    async def _on_alert(self, payload: dict) -> None:
        if not payload.get("is_test") and self.red_flags.hides(
                str(payload.get("platform") or ""), "", str(payload.get("username") or "")):
            log.info("[alert/%s] hidden: %s is red-flagged", payload.get("kind"), payload.get("username"))
            return
        if payload.get("source") == "platform":
            # Sub / resub / gift from an adapter: adapters don't see overlay settings.
            ov = self.config.get("overlay") or {}
            payload["duration_ms"] = max(1500, min(30000, int(ov.get("alert_duration_ms") or 6000)))
            await self._award_alert_points(payload)
        self.recent_alerts.append(payload)
        if len(self.recent_alerts) > self.recent_alerts_max:
            del self.recent_alerts[: -self.recent_alerts_max]
        self.state.recent_alerts = self.recent_alerts
        if self.state.ws_manager:
            try:
                await self.state.ws_manager.broadcast({"type": "alert", "data": payload})
            except Exception:
                log.exception("alert WS broadcast failed")
        tag = "TEST" if payload.get("is_test") else payload.get("kind")
        log.info("[alert/%s] %s", tag, payload.get("headline"))
        try:
            self.credits.note_alert(
                payload.get("kind") or "",
                payload.get("platform") or "",
                payload.get("username") or "",
            )
        except Exception:
            log.exception("credits alert tag failed")

    async def _award_alert_points(self, payload: dict) -> None:
        """Points for a real sub / resub / follow / gift (never Alert-test ones).

        `points.sub_points` per sub or resub, `points.follow_points` once per viewer,
        `points.gift_points` to the gifter for each sub gifted. Sets `points_awarded`.
        """
        self._sync_live_config()
        pts = self.config.get("points") or {}
        if not pts.get("enabled") or payload.get("is_test"):
            return
        kind = payload.get("kind") or ""

        def amount(key: str) -> int:
            try:
                return max(0, int(pts.get(key, DEFAULTS["points"][key])))
            except (TypeError, ValueError):
                return 0

        once = False
        if kind in ("subscribe", "resub"):
            delta, reason = amount("sub_points"), "subscribed"
        elif kind == "follow":
            delta, reason, once = amount("follow_points"), "followed", True
        elif kind == "gift":
            qty = max(1, int(payload.get("qty") or 1))
            delta, reason = amount("gift_points") * qty, f"gifted {qty} sub(s)"
        else:
            return
        try:
            res = await self.store.award_for_alert(
                payload.get("platform") or "",
                payload.get("user_id") or "",
                payload.get("username") or "",
                payload.get("display_name") or "",
                delta,
                reason,
                kind,
                once=once,
            )
        except Exception:
            log.exception("alert points failed")
            return
        if res:
            payload["points_awarded"] = res["delta"]
            log.info("points +%s → %s (%s, bal %s)", res["delta"], payload.get("display_name"), reason, res["balance"])

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
                reply_text = result.get("reply") if isinstance(result, dict) else None
                if reply_text:
                    await self.bus.publish_reply(ChatReply(
                        platform=req.platform,
                        message=str(reply_text),
                        reply_to_user=(req.user.display_name or req.user.username) if req.user else "",
                        target_platform=req.platform,
                    ))
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

    cfg_token = (config.get("points") or {}).get("admin_token")
    if is_placeholder_token(cfg_token):
        generated = resolve_admin_token(config, ROOT)
        if generated:
            log.warning(
                "points.admin_token is unset or a placeholder — the admin dashboard uses the "
                "generated token in data/admin_token.txt: %s",
                generated,
            )
        else:
            log.error("No usable admin token — set points.admin_token in config.yaml")

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
