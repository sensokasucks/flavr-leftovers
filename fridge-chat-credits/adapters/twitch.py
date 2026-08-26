"""Twitch chat over anonymous IRC. No OAuth needed for read-only listen."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Optional

from adapters.base import BaseAdapter
from core.models import ChatEvent, ChatUser, Platform

log = logging.getLogger("adapters.twitch")

HOST = "irc.chat.twitch.tv"
PORT = 6667

PRIVMSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<nick>[^!]+)![^ ]+ PRIVMSG #(?P<chan>[^ ]+) :(?P<msg>.*)$"
)


def _parse_tags(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v.replace("\\s", " ")
        else:
            out[part] = ""
    return out


class TwitchAdapter(BaseAdapter):
    platform = Platform.TWITCH

    def __init__(self, config: dict, bus):
        super().__init__(config, bus)
        cfg = config.get("twitch", {})
        self.channel = (cfg.get("channel") or "").strip().lstrip("#").lower()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._writer: Optional[asyncio.StreamWriter] = None

    async def start(self) -> None:
        if not self.channel or self.channel.startswith("your_"):
            log.warning("Twitch channel not set — adapter off")
            return
        self._running = True
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="twitch-irc")
        log.info("Twitch IRC listening on #%s", self.channel)

    async def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        backoff = 3.0
        nick = f"justinfan{random.randint(10000, 99999)}"
        while self._running:
            try:
                reader, writer = await asyncio.open_connection(HOST, PORT)
                self._writer = writer
                writer.write(
                    (
                        "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                        f"NICK {nick}\r\n"
                        f"JOIN #{self.channel}\r\n"
                    ).encode("utf-8")
                )
                await writer.drain()
                log.info("Twitch IRC connected as %s", nick)
                backoff = 3.0
                buf = ""
                while self._running:
                    data = await reader.read(4096)
                    if not data:
                        break
                    buf += data.decode("utf-8", "ignore")
                    while "\r\n" in buf:
                        line, buf = buf.split("\r\n", 1)
                        await self._on_line(writer, line)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Twitch IRC error: %s — retry in %.1fs", e, backoff)
            if not self._running:
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 1.5, 30.0)

    async def _on_line(self, writer: asyncio.StreamWriter, line: str) -> None:
        if not line:
            return
        if line.startswith("PING"):
            writer.write(b"PONG :tmi.twitch.tv\r\n")
            await writer.drain()
            return
        m = PRIVMSG_RE.match(line)
        if not m:
            return
        tags = _parse_tags(m.group("tags") or "")
        nick = m.group("nick")
        msg = m.group("msg") or ""
        display = tags.get("display-name") or nick
        badges = (tags.get("badges") or "").split(",")
        badge_names = [b.split("/")[0] for b in badges if b]
        user = ChatUser(
            platform=Platform.TWITCH,
            id=tags.get("user-id") or nick,
            username=nick,
            display_name=display,
            is_mod=tags.get("mod") == "1" or "moderator" in badge_names or "broadcaster" in badge_names,
            is_vip="vip" in badge_names,
            is_subscriber=tags.get("subscriber") == "1" or "subscriber" in badge_names,
            badges=badge_names,
            color=tags.get("color") or None,
        )
        await self._emit(ChatEvent(
            platform=Platform.TWITCH,
            user=user,
            message=msg,
            message_id=tags.get("id"),
        ))
