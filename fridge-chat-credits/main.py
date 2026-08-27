#!/usr/bin/env python3
"""
Fridge Chat Credits — standalone unique-chatter credits roll.

Adapters (Twitch / Kick / YouTube / Stream Core ingest) feed an in-process
bus. The roster keeps one row per (platform, username). An HTML overlay
renders a configurable end-credits marquee for XSplit / OBS.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.kick import KickAdapter
from adapters.stream_core import StreamCoreIngest
from adapters.twitch import TwitchAdapter
from adapters.youtube import YouTubeAdapter
from api.server import AppState, create_app, load_theme
from core.cast import CastBoard, roster_payload
from core.config import load_config
from core.event_bus import EventBus
from core.models import ChatEvent, ChatUser, Platform
from core.roster import Roster

log = logging.getLogger("main")


class ChatCredits:
    def __init__(self, config: dict):
        self.config = config
        self.bus = EventBus()
        ignore = list(config.get("roster", {}).get("ignore_usernames") or [])
        if config.get("roster", {}).get("ignore_own_channel", True):
            kick_slug = (config.get("kick") or {}).get("channel_slug") or ""
            tw = (config.get("twitch") or {}).get("channel") or ""
            if kick_slug and not kick_slug.startswith("YOUR_"):
                ignore.append(kick_slug)
            if tw and not tw.startswith("your_"):
                ignore.append(tw)
        session = Path(config.get("app", {}).get("session_file") or "data/session.json")
        if not session.is_absolute():
            session = ROOT / session
        self.roster = Roster(
            path=session,
            ignore=ignore,
            min_len=int(config.get("roster", {}).get("min_message_length") or 1),
        )
        self.roster.load()
        self.state = AppState()
        self.state.config = config
        self.state.roster = self.roster
        self.state.root = ROOT
        self.state.bus = self.bus
        self.cast = CastBoard(ROOT, allow_alert_groups=False)
        self.cast.set_style((config.get("credits") or {}).get("style_id") or "names")
        self.state.cast = self.cast
        load_theme(self.state)
        self.state.theme["style_id"] = self.cast.style_id
        self.state.theme["style"] = self.cast.get_style().get("style") or "names"
        if os.environ.get("CREDITS_DEMO") == "1":
            # Preview pane is not a transparent compositor — use a solid stage.
            if (self.state.theme.get("background") or "transparent") == "transparent":
                self.state.theme["background"] = "#000"
        self.state.play["mode"] = self.state.theme.get("mode") or "loop"
        self.state.apply_config = self.apply_runtime_config
        self.adapters: dict = {}
        self.state.adapters = self.adapters
        self._save_task: asyncio.Task | None = None
        self._pending_broadcast = False

    async def start(self) -> None:
        self.bus.on_chat(self._on_chat)
        self.roster.on_change(self._mark_broadcast)

        twitch_cfg = self.config.get("twitch") or {}
        if twitch_cfg.get("enabled"):
            tw = TwitchAdapter(self.config, self.bus)
            await tw.start()
            self.adapters["twitch"] = tw

        kick_cfg = self.config.get("kick") or {}
        if kick_cfg.get("enabled"):
            kick = KickAdapter(self.config, self.bus)
            await kick.start()
            self.adapters["kick"] = kick

        yt_cfg = self.config.get("youtube") or {}
        if yt_cfg.get("enabled"):
            yt = YouTubeAdapter(self.config, self.bus)
            await yt.start()
            self.adapters["youtube"] = yt

        ingest_cfg = (self.config.get("ingest") or {}).get("stream_core") or {}
        if ingest_cfg.get("enabled"):
            if kick_cfg.get("enabled"):
                log.warning(
                    "Both Kick adapter and Stream Core ingest are on — "
                    "you will see duplicate Kick names. Disable one."
                )
            ingest = StreamCoreIngest(self.config, self.bus)
            await ingest.start()
            self.adapters["stream_core"] = ingest

        save_every = float(self.config.get("app", {}).get("save_every_sec") or 10)
        self._save_task = asyncio.create_task(self._persist_loop(save_every), name="persist")
        if os.environ.get("CREDITS_DEMO") == "1" and not self.roster.chatters:
            await self._seed_demo()
        log.info(
            "Chat Credits ready — %s unique so far, adapters=%s",
            len(self.roster.chatters),
            list(self.adapters.keys()) or "(none configured)",
        )

    async def stop(self) -> None:
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        for adapter in self.adapters.values():
            await adapter.stop()
        self.roster.save()
        log.info("Chat Credits stopped")

    def apply_runtime_config(self, config: dict) -> None:
        """Hot-apply ignore list / theme. Adapter toggles still need a restart."""
        self.config = config
        self.state.config = config
        roster_cfg = config.get("roster") or {}
        ignore = list(roster_cfg.get("ignore_usernames") or [])
        if roster_cfg.get("ignore_own_channel", True):
            kick_slug = (config.get("kick") or {}).get("channel_slug") or ""
            tw = (config.get("twitch") or {}).get("channel") or ""
            if kick_slug and not str(kick_slug).startswith("YOUR_"):
                ignore.append(kick_slug)
            if tw and not str(tw).startswith("your_"):
                ignore.append(tw)
        self.roster.ignore = {n.lower().strip() for n in ignore if n}
        self.roster.min_len = max(0, int(roster_cfg.get("min_message_length") or 1))
        if isinstance(config.get("credits"), dict):
            self.state.theme.update(config["credits"])

    def _mark_broadcast(self) -> None:
        self._pending_broadcast = True

    async def _on_chat(self, event: ChatEvent) -> None:
        self.roster.ingest(event)

    async def _seed_demo(self) -> None:
        """Preview-only names so the roll has something to crawl."""
        samples = [
            (Platform.TWITCH, "AriaVox", True),
            (Platform.TWITCH, "pixelranch", False),
            (Platform.KICK, "NeonHarbor", False),
            (Platform.KICK, "mod_maple", True),
            (Platform.YOUTUBE, "Lo-Fi Lynx", False),
            (Platform.TWITCH, "copperkettle", False),
            (Platform.KICK, "questinggnat", False),
            (Platform.YOUTUBE, "StudioMoth", False),
            (Platform.TWITCH, "emberwalk", False),
            (Platform.KICK, "saltandbit", False),
            (Platform.TWITCH, "nightorchard", False),
            (Platform.YOUTUBE, "viscounttea", False),
            (Platform.KICK, "bramblecast", False),
            (Platform.TWITCH, "softcheckpoint", False),
            (Platform.MANUAL, "the_crew", False),
            (Platform.TWITCH, "riverglass", False),
            (Platform.KICK, "hexlane", False),
            (Platform.YOUTUBE, "paperlantern", False),
            (Platform.TWITCH, "duskparcel", False),
            (Platform.KICK, "wildstatic", False),
            (Platform.TWITCH, "lowpolyfarm", False),
            (Platform.KICK, "coastalping", False),
            (Platform.YOUTUBE, "amberthread", False),
            (Platform.TWITCH, "silentcart", False),
            (Platform.KICK, "fogandfiber", False),
            (Platform.TWITCH, "rookandrelay", False),
            (Platform.YOUTUBE, "tinwhistle", False),
            (Platform.KICK, "copperline", False),
            (Platform.TWITCH, "moonwell", False),
            (Platform.KICK, "atlascrumb", False),
            (Platform.YOUTUBE, "firstlight", False),
            (Platform.TWITCH, "peatandpine", False),
            (Platform.KICK, "silverlatch", False),
            (Platform.TWITCH, "harborfinch", False),
            (Platform.YOUTUBE, "quiltedbyte", False),
            (Platform.KICK, "northkiln", False),
        ]
        for plat, name, is_mod in samples:
            name = name.strip()
            await self.bus.publish_chat(ChatEvent(
                platform=plat,
                user=ChatUser(
                    platform=plat,
                    id=name,
                    username=name,
                    display_name=name,
                    is_mod=is_mod,
                ),
                message="(demo)",
            ))
        log.info("Seeded %s demo chatters for preview", len(samples))

    async def _persist_loop(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            try:
                self.roster.save_if_dirty()
            except Exception:
                log.exception("session save failed")
            if self._pending_broadcast and self.state.ws:
                self._pending_broadcast = False
                if not self.state.play.get("freeze"):
                    try:
                        await self.state.ws.broadcast(
                            {"type": "roster", "data": roster_payload(self.state)}
                        )
                    except Exception:
                        log.exception("roster broadcast failed")


async def _run() -> None:
    config = load_config(ROOT)
    level = str(config.get("app", {}).get("log_level") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    app_core = ChatCredits(config)
    await app_core.start()

    host = os.environ.get("CREDITS_HOST") or config.get("app", {}).get("host") or "127.0.0.1"
    port = int(os.environ.get("CREDITS_PORT") or config.get("app", {}).get("port") or 3854)
    fastapi_app = create_app(app_core.state)

    uv_config = uvicorn.Config(
        fastapi_app,
        host=host,
        port=port,
        log_level=level.lower(),
        lifespan="on",
    )
    server = uvicorn.Server(uv_config)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _ask_stop(*_):
        stop.set()
        server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _ask_stop)
        except NotImplementedError:
            pass

    log.info("HTTP on http://%s:%s  overlay /overlay/credits.html", host, port)
    try:
        await server.serve()
    finally:
        await app_core.stop()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
